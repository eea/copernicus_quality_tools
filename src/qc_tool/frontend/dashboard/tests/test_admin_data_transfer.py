"""The administrator transfer workflow keeps review and authority server-side."""

import re
import tempfile
from copy import deepcopy
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils.html import escape

from qc_tool.database.transfers import service
from qc_tool.database.transfers.components import EXPORT_COMPONENT_CHOICES
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.authentication.maintenance import (
    ORIGIN_DATABASE, cookie_session, login_without_database_writes,
)
from qc_tool.frontend.dashboard.services import maintenance
from qc_tool.frontend.dashboard.forms.data_transfers import ExportSelectionForm, EXPORT_COMPONENTS


class AdminDataTransferTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings_override = override_settings(
            QC_TOOL_MAINTENANCE_DIR=directory.name + "/maintenance",
            QC_TOOL_TRANSFER_DIR=directory.name + "/transfers",
            MAINTENANCE_MODE=False,
        )
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        self.administrator = get_user_model().objects.create_superuser(
            username="transfer-administrator", password="test-password",
            email="admin@example.test",
        )
        self.user = get_user_model().objects.create_user(username="selected-account")
        self.other = get_user_model().objects.create_user(username="other-account")
        self.client.force_login(self.administrator)
        self.url = reverse("admin_data_transfer")
        self.export_url = reverse("admin_backup_export")
        self.import_url = reverse("admin_backup_import")
        self.operation_id = "812d54c5-f69b-4f51-9e25-d4cbbd9a35da"
        self.plan = {
            "profile": "accounts", "plan_hash": "a" * 64,
            "package_sha256": "b" * 64, "target_label": "test destination",
            "confirmation_text": "test destination", "counts": {"accounts": 1},
            "account_mappings": [{"source_id": "source-alice", "username": "alice", "email": "alice@example.test"}],
            "blockers": [], "warnings": [], "exclusions": ["Credentials"],
            "can_apply": True,
        }
        self.operation = {
            "id": self.operation_id, "kind": "import", "status": "planned",
            "plan": self.plan, "downloadable": False,
        }
        self.patch("list_operations", return_value=[])
        self.database_availability = self.patch("database_availability", create=True, return_value={
            "ready": False, "message": "Full database backups require PostgreSQL and its client tools.",
            "can_create_restore_database": False, "current_database": "qc_tool_live",
        })
        self.control_state = {"active_database": "qc_tool_live", "previous_database": "", "revision": 0,
                              "has_selection": False, "rollback_requires_credentials": False, "rollback_blockers": []}
        self.patch("database_control_status", create=True, return_value=self.control_state)
        self.activation_review = {
            "can_apply": False, "blockers": [], "review_hash": "e" * 64,
            "target_database": "qc_tool_restore", "source_database": "qc_tool_live",
            "revision": 0, "requires_credentials": False,
        }
        self.patch("activation_preview", create=True, return_value=self.activation_review)

    def patch(self, name, **kwargs):
        mocked = patch.object(service, name, **kwargs)
        result = mocked.start()
        self.addCleanup(mocked.stop)
        return result

    def test_busy_transfer_uses_status_checks_instead_of_a_permanent_error(self):
        from qc_tool.database.transfers.errors import TransferBusy
        self.patch("get_operation", return_value={**self.operation, "kind": "export", "status": "completed"})
        release = self.patch("release_export_package", side_effect=TransferBusy("Another maintenance action is in progress."))
        response = self.client.post(self.url + "?tab=backups", {
            "operation_id": self.operation_id, "action": "release_package", "confirmed_release": "on",
        })
        self.assertContains(response, "Another action is finishing", status_code=409)
        self.assertContains(response, "Your request will not be retried automatically", status_code=409)
        self.assertContains(response, "data-admin-busy-url", status_code=409)
        release.assert_called_once_with(self.operation_id, actor=self.administrator)

    def zip_handle(self, content):
        handle = self.enterContext(tempfile.TemporaryFile())
        handle.write(content)
        handle.seek(0)
        return handle

    def operation_patch(self, **updates):
        operation = deepcopy(self.operation)
        operation.update(updates)
        return self.patch("get_operation", return_value=operation)

    def ready(self):
        enabled = maintenance.enable(self.administrator, expected_generation=0)
        maintenance.advance(expected_generation=enabled["generation"])
        return maintenance.read_status()["generation"]

    def test_administrator_discovers_one_import_and_one_export_workflow(self):
        self.assertContains(self.client.get(reverse("admin:index")), f'href="{reverse("admin_maintenance")}"')
        response = self.client.get(reverse("admin_maintenance"))
        self.assertContains(response, self.export_url)
        self.assertContains(response, self.import_url)
        self.assertNotContains(response, "Export records")
        self.assertNotContains(response, "Export users")
        self.assertNotContains(response, 'name="scope"')
        self.assertNotContains(response, 'name="package"')

    def test_unknown_task_opens_export_without_starting_a_transfer(self):
        preview = self.patch("export_preview")
        stage = self.patch("stage_import")
        response = self.client.get(self.url, {"tab": "not-a-transfer-task"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["transfer_task"], "export")
        self.assertContains(response, 'value="preview_export"')
        self.assertNotContains(response, 'name="package"')
        preview.assert_not_called()
        stage.assert_not_called()

    def test_older_user_packages_stay_in_database_administration(self):
        self.operation_patch()
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertEqual(response.context["admin_section"], "maintenance")
        self.assertEqual(response.context["transfer_area"], "users")
        self.assertContains(response, "<h1>Import details</h1>", html=True)
        self.assertContains(response, "Back to Restore from ZIP")

    def test_export_always_contains_complete_database_and_has_no_portable_scope_picker(self):
        response = self.client.get(self.url, {"tab": "export"})
        self.assertEqual(response.context["transfer_task"], "export")
        self.assertTrue(response.context["native_transfer"])
        self.assertEqual(response.context["export_form"]["scope"].value(), "database")
        self.assertContains(response, '<input type="hidden" name="scope" value="database" id="id_scope">', html=True)
        self.assertContains(response, "password hashes")
        self.assertNotContains(response, 'type="radio" name="scope"')
        self.assertNotContains(response, 'name="users"')

    def test_export_choice_and_review_show_only_the_backup_journey(self):
        self.ready()
        self.native_ready()
        self.patch("export_preview", return_value={
            "review_hash": "c" * 64, "counts": {"tables": 20},
        })
        create = self.patch("create_export")

        responses = (
            self.client.get(self.url, {"tab": "export"}),
            self.client.post(self.url, {
                "action": "preview_export", "scope": "database", "components": ["boundaries"],
            }),
        )

        for response in responses:
            with self.subTest(review=bool(response.context["export_review"])):
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "data-maintenance-banner", count=1)
                self.assertContains(response, "Maintenance is on", count=1)
                self.assertNotContains(response, 'aria-label="Maintenance tasks"')
                self.assertNotContains(response, 'id="database-recovery"')
                self.assertNotContains(response, 'id="transfer-history"')
                self.assertNotContains(response, 'id="saved-backups"')
                self.assertNotContains(response, 'id="backup-files"')
        create.assert_not_called()

    def test_every_export_bookmark_defaults_to_all_optional_package_sections(self):
        for query in ({"tab": "export"}, {"tab": "backup"},
                      {"section": "records", "tab": "export"}, {"section": "users", "tab": "export"}):
            with self.subTest(query=query):
                response = self.client.get(self.url, query)
                self.assertEqual(list(response.context["export_form"]["components"].value()), list(EXPORT_COMPONENTS))
                self.assertEqual(response.context["transfer_task"], "export")
                self.assertContains(response, 'name="components"')
                self.assertNotContains(response, "Records only")

    def test_component_selection_reaches_review_confirmation_edit_and_maintenance_links(self):
        self.native_ready()
        preview = self.patch("export_preview", return_value={"review_hash": "c" * 64, "counts": {"tables": 20}})
        for components in (["boundaries", "artifacts"], []):
            with self.subTest(components=components):
                preview.return_value["components"] = [
                    {"key": key, "label": label, "selected": key in components,
                     "status": "included" if key in components else "omitted",
                     "files_count": 0, "byte_count": 0}
                    for key, label in EXPORT_COMPONENT_CHOICES
                ]
                response = self.client.post(self.url, {"action": "preview_export", "scope": "database", "components": components})
                self.assertEqual(response.status_code, 200)
                preview.assert_called_with({"profile": "database", "user_ids": [], "components": components}, actor=self.administrator)
                for value in components:
                    self.assertContains(response, f'<input type="hidden" name="components" value="{value}">', html=True)
                self.assertEqual(response.context["export_selection"]["components"], components)
                if not components:
                    self.assertContains(response, "No optional files or server settings selected.")
                    self.assertNotContains(response, '<caption>Package sections</caption>', html=True)
                    omitted = re.search(
                        r'<details\b([^>]*)>\s*<summary>Omitted contents</summary>(.*?)</details>',
                        response.content.decode(response.charset), re.DOTALL,
                    )
                    self.assertIsNotNone(omitted)
                    self.assertNotIn("open", omitted.group(1))
                    for _key, label in EXPORT_COMPONENT_CHOICES:
                        self.assertIn(label, omitted.group(2))
                edit_query = parse_qs(urlsplit(response.context["edit_export_url"]).query)
                self.assertEqual(edit_query.get("components", []), components)
                self.assertEqual(edit_query["components_selected"], ["true"])
                back = self.client.get(response.context["edit_export_url"])
                self.assertEqual(back.context["export_form"]["components"].value(), components)
                destination = parse_qs(urlsplit(response.context["maintenance_url"]).query)["next"][0]
                self.assertEqual(parse_qs(urlsplit(destination).query), {**edit_query, "from": ["backups"]})

    def test_invalid_component_or_old_portable_export_scope_never_reaches_service(self):
        preview = self.patch("export_preview")
        for payload in ({"scope": "database", "components": ["unknown-section"]},
                        {"scope": "application"}, {"scope": "all_accounts"}, {"scope": "selected_accounts"}):
            with self.subTest(payload=payload):
                response = self.client.post(self.url, {"action": "preview_export", **payload})
                self.assertContains(response, "Select a valid choice", status_code=400)
        preview.assert_not_called()

    def test_export_review_distinguishes_selected_omitted_and_unavailable_sections(self):
        self.ready()
        self.native_ready()
        self.patch("export_preview", return_value={
            "profile": "database", "review_hash": "c" * 64, "counts": {"tables": 20},
            "components": [
                {"key": "boundaries", "label": "Boundary packages", "selected": True, "status": "unavailable", "files_count": 0, "byte_count": 0},
                {"key": "artifacts", "label": "QC results and artifacts", "selected": False, "status": "omitted", "files_count": 0, "byte_count": 0},
                {"key": "specifications", "label": "Original product specifications", "selected": True, "status": "included", "files_count": 2, "byte_count": 2048},
                {"key": "deliveries", "label": "Retained delivery ZIPs", "selected": True, "status": "partial", "files_count": 1, "byte_count": 1024},
            ],
            "notes": ["One retained ZIP is missing.", "Keep this backup private."],
        })
        response = self.client.post(self.url, {
            "action": "preview_export", "scope": "database",
            "components": ["boundaries", "specifications", "deliveries"],
        })
        for text in (
            "Package sections", "Unavailable", "Omitted", "Included", "Partial",
            "Boundary packages", "Original product specifications",
            "One retained ZIP is missing.", "Keep this backup private.",
        ):
            self.assertContains(response, text)
        self.assertContains(response, '<th scope="row">Retained delivery ZIPs</th>', html=True)
        self.assertNotContains(response, '<th scope="row">QC results and artifacts</th>', html=True)
        self.assertContains(response, '<li>QC results and artifacts</li>', html=True)
        self.assertNotContains(response, "Record-package limit")
        self.assertNotContains(response, "Review full database backup")



    def test_export_review_explains_storage_and_package_capacity(self):
        self.ready()
        self.native_ready()
        self.patch("export_preview", return_value={
            "profile": "database", "review_hash": "c" * 64, "counts": {},
            "blockers": ["Backup storage is too small."],
            "storage_capacity": {
                "file_bytes": 2 * 1024**3, "records_bytes": 1024,
                "estimated_database_bytes": None, "estimated_package_bytes": 2 * 1024**3 + 2048,
                "required_free_bytes": 3 * 1024**3, "free_bytes": 1024**3,
                "reserve_bytes": 512 * 1024**2, "max_archive_bytes": 16 * 1024**3,
                "max_member_bytes": 16 * 1024**3, "max_total_bytes": 64 * 1024**3,
            },
        })
        response = self.client.post(self.url, {
            "action": "preview_export", "scope": "database", "components": ["artifacts"],
        })
        self.assertContains(response, "Capacity estimate")
        self.assertContains(response, "Free space on backup volume")
        self.assertContains(response, "Estimated free space required, including reserve")
        self.assertContains(response, "Single file limit")
        self.assertContains(response, "Expanded contents limit")
        self.assertContains(response, 'value="export" disabled')

    def test_completed_export_release_requires_confirmation_and_preserves_completed_history(self):
        self.operation_patch(kind="export", profile="application", status="completed", plan=None,
                             downloadable=True, recoverable=False, runner_active=False, releasable=True)
        release = self.patch("release_export_package", create=True, return_value={
            **self.operation, "kind": "export", "profile": "application", "status": "completed",
            "plan": None, "downloadable": False, "payload_released_at": "2026-10-23T10:00:00+00:00",
        })
        page = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(page, 'name="action" value="release_package"')
        response = self.client.post(self.url, {"action": "release_package", "operation_id": self.operation_id})
        self.assertContains(response, "Confirm that a verified copy", status_code=409)
        release.assert_not_called()
        response = self.client.post(self.url, {
            "action": "release_package", "operation_id": self.operation_id, "confirmed_release": "on",
        })
        release.assert_called_once_with(self.operation_id, actor=self.administrator)
        self.assertContains(response, "Export package released. Transfer history is retained.")
        self.assertEqual(response.context["operation"]["status"], "completed")
        self.assertNotContains(response, reverse("admin_data_transfer_download", args=[self.operation_id]))
        self.assertNotContains(response, 'value="release_package"')

    def test_import_packages_cannot_be_released_from_export_cleanup(self):
        self.operation_patch(kind="import", profile="accounts", status="completed", plan=None, downloadable=True)
        release = self.patch("release_export_package", create=True)
        page = self.client.get(self.url, {"operation": self.operation_id})
        self.assertNotContains(page, 'value="release_package"')
        response = self.client.post(self.url, {
            "action": "release_package", "operation_id": self.operation_id, "confirmed_release": "on",
        })
        self.assertContains(response, "Only a completed export package", status_code=409)
        release.assert_not_called()

    def test_backup_file_deletion_returns_to_storage_without_post_resubmission(self):
        self.operation_patch(kind="export", profile="database", status="completed", plan=None, releasable=True)
        release = self.patch("release_export_package", return_value={**self.operation,
            "kind": "export", "status": "completed", "payload_released_at": "2026-10-23T10:00:00Z"})
        response = self.client.post(self.url, {"action": "release_package", "operation_id": self.operation_id,
            "confirmed_release": "on", "return_to_backup_files": "on"})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response["Location"], self.export_url + "#prepared-backups")
        self.assertIn("no-store", response["Cache-Control"])
        release.assert_called_once_with(self.operation_id, actor=self.administrator)

    def test_interrupted_export_release_has_no_download_and_can_be_finished(self):
        self.operation_patch(kind="export", profile="application", status="completed", plan=None,
                             downloadable=True, releasable=True,
                             package_release_requested_at="2026-10-23T10:00:00+00:00")
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(response, "Finish deleting ZIP")
        self.assertNotContains(response, reverse("admin_data_transfer_download", args=[self.operation_id]))

    def test_released_export_history_preserves_completion_and_hides_download(self):
        self.patch("list_operations", return_value=[{
            "id": self.operation_id, "kind": "export", "profile": "database", "status": "completed",
            "downloadable": True, "payload_released_at": "2026-10-23T10:00:00+00:00",
        }])
        response = self.client.get(self.url, {"tab": "activity"})
        self.assertNotContains(response, self.operation_id)
        self.assertNotContains(response, reverse("admin_data_transfer_download", args=[self.operation_id]))


    def test_backup_task_keeps_its_full_scope_despite_conflicting_query_selection(self):
        response = self.client.get(self.url, {
            "tab": "backup", "scope": "selected_accounts", "users": [self.user.pk],
        })
        self.assertEqual(response.context["transfer_task"], "export")
        self.assertEqual(response.context["export_form"]["scope"].value(), "database")
        self.assertTrue(response.context["native_transfer"])
        self.assertNotContains(response, 'name="users"')
        self.assertNotContains(response, 'type="radio" name="scope"')

    def test_existing_full_backup_link_opens_the_backup_task(self):
        response = self.client.get(self.url, {"tab": "export", "scope": "database"})
        self.assertEqual(response.context["transfer_task"], "export")
        self.assertEqual(response.context["export_form"]["scope"].value(), "database")

    def test_upload_task_does_not_guess_the_package_profile_or_require_native_tools(self):
        response = self.client.get(self.url, {"tab": "import"})
        self.assertEqual(response.context["transfer_task"], "import")
        self.assertFalse(response.context["native_transfer"])
        self.assertFalse(response.context["native_import"])
        self.assertContains(response, 'name="package"')
        self.assertNotContains(response, self.database_availability.return_value["message"])
        service.activation_preview.assert_not_called()

    def test_exports_explain_native_availability_without_portable_schema_warnings(self):
        self.incompatible_schema()
        response = self.client.get(self.url, {"tab": "history"})
        self.assertEqual(response.context["transfer_task"], "export")
        self.assertContains(response, '<h1>Create a backup</h1>', html=True)
        self.assertNotContains(response, "missing table qc_database_transfer_receipt")
        self.assertContains(response, self.database_availability.return_value["message"])
        self.assertNotContains(response, "Maintenance is off")

    def test_operation_profile_determines_task_despite_a_conflicting_navigation_query(self):
        operation = self.operation_patch()
        for kind, profile, expected in (
            ("export", "database", "export"),
            ("export", "application", "export"),
            ("export", "accounts", "export"),
            ("import", "application", "import"),
            ("import", "database", "import"),
        ):
            with self.subTest(kind=kind, profile=profile):
                operation.return_value.update(kind=kind, profile=profile, status="completed", plan=None)
                response = self.client.get(self.url, {
                    "tab": "history", "scope": "selected_accounts", "operation": self.operation_id,
                })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["transfer_task"], expected)
                self.assertEqual(response.context["native_transfer"], profile == "database")
        service.activation_preview.assert_not_called()


    def test_failed_export_preview_preserves_selected_sections_for_edit_and_maintenance(self):
        self.native_ready()
        self.patch("export_preview", side_effect=service.TransferError("A retained file is unavailable."))
        for components in (["boundaries"], []):
            with self.subTest(components=components):
                response = self.client.post(self.url, {
                    "action": "preview_export", "scope": "database", "components": components,
                })
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.context["transfer_task"], "export")
                self.assertEqual(response.context["export_form"]["components"].value(), components)
                expected = {"components_selected": ["true"]}
                if components:
                    expected["components"] = components
                self.assertEqual(parse_qs(urlsplit(response.context["edit_export_url"]).query), expected)
                destination = parse_qs(urlsplit(response.context["maintenance_url"]).query)["next"][0]
                self.assertEqual(parse_qs(urlsplit(destination).query), {**expected, "from": ["backups"]})


    def test_export_selection_does_not_query_account_records(self):
        with self.assertNumQueries(0):
            form = ExportSelectionForm()
            rendered = str(form)
        self.assertNotIn('name="users"', rendered)
        self.assertIn('name="components"', rendered)

    def test_anonymous_uses_admin_login(self):
        self.client.logout()
        self.assertRedirects(
            self.client.get(self.url), reverse("admin_login") + "?next=" + self.url,
            fetch_redirect_response=False,
        )

    def test_qc_administrator_role_can_open_workflow(self):
        administrator = get_user_model().objects.create_user(username="role-administrator")
        administrator.groups.add(Group.objects.get(name=Role.ADMIN.value))
        self.client.force_login(administrator)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_staff_and_product_managers_cannot_access_transfer_or_download(self):
        for role in (None, Role.PRODUCT_MANAGER):
            user = get_user_model().objects.create_user(username="denied-" + str(role), is_staff=True)
            if role:
                user.groups.add(Group.objects.get(name=role.value))
            else:
                get_user_model().objects.filter(pk=user.pk).update(is_staff=True)
                user.refresh_from_db()
            self.client.force_login(user)
            with self.subTest(role=role):
                self.assertEqual(self.client.get(self.url).status_code, 403)
                self.assertEqual(self.client.post(self.url, {"action": "preview_export"}).status_code, 403)
                self.assertEqual(self.client.get(reverse("admin_data_transfer_status", args=[self.operation_id])).status_code, 403)
                self.assertEqual(self.client.get(reverse("admin_data_transfer_download", args=[self.operation_id])).status_code, 403)
                self.assertNotContains(self.client.get(reverse("admin:index")), f'href="{self.url}"')

    @override_settings(SESSION_SAVE_EVERY_REQUEST=True)
    def test_get_does_not_mutate_business_or_session_records(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("private", response["Cache-Control"])
        self.assertEqual([
            item["sql"] for item in queries
            if item["sql"].lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER "))
        ], [])

    def test_owned_maintenance_shows_operation_and_disables_competing_transfer_controls(self):
        self.ready()
        with patch("qc_tool.frontend.dashboard.views.admin_data_transfer.active_operation", return_value={"operation_id": self.operation_id, "kind": "import"}):
            response = self.client.get(self.url, {"tab": "export"})
        self.assertContains(response, "Another administrator task must finish before you can continue.")
        self.assertNotContains(response, "View current task")
        self.assertContains(response, 'value="preview_export" disabled')
        self.assertNotContains(response, 'value="upload"')

    def test_transfer_banner_distinguishes_a_runner_from_a_recovery_pin(self):
        self.ready()
        listed = self.patch("list_operations", return_value=[{
            "id": self.operation_id, "kind": "export", "status": "running",
            "runner_active": True, "recoverable": False,
        }])
        with patch("qc_tool.frontend.dashboard.views.admin_data_transfer.active_operation", return_value={"operation_id": self.operation_id, "kind": "export"}):
            response = self.client.get(self.url, {"tab": "backups"})
            self.assertContains(response, "A database task is in progress")
            self.assertContains(response, 'data-transfer-status-url="' + reverse("admin_data_transfer_status", args=[self.operation_id]) + '"')
            self.assertContains(response, 'href="' + escape(response.context["admin_busy_refresh_url"]) + '" data-transfer-refresh')
            listed.return_value = [{"id": self.operation_id, "kind": "export", "status": "running", "recoverable": True}]
            response = self.client.get(self.url, {"tab": "backups"})
        self.assertContains(response, "A database task needs recovery")
        self.assertNotContains(response, "A database task is in progress")
        self.assertNotContains(response, "data-transfer-status-url=")

    def test_csrf_protects_preview_and_upload_before_service(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.administrator)
        preview = self.patch("export_preview")
        stage = self.patch("stage_import")
        self.assertEqual(client.post(self.url, {"action": "preview_export", "scope": "selected_accounts", "users": [self.user.pk]}).status_code, 403)
        self.assertEqual(client.post(self.url, {"action": "upload"}).status_code, 403)
        preview.assert_not_called()
        stage.assert_not_called()




    def test_export_passes_reviewed_sections_hash_and_generation_without_accepting_rows(self):
        generation = self.ready()
        self.native_ready()
        create = self.patch("create_export", return_value={"id": self.operation_id, "profile": "database", "kind": "export", "status": "queued"})
        response = self.client.post(self.url, {"action": "export", "scope": "database", "components": ["boundaries"],
            "reviewed_hash": "c" * 64, "generation": generation, "records": "untrusted content", "users": [self.user.pk]})
        self.assertRedirects(response, f"{self.export_url}?operation={self.operation_id}#transfer-operation",
                             status_code=303, fetch_redirect_response=False)
        create.assert_called_once_with({"profile": "database", "user_ids": [], "components": ["boundaries"]},
            actor=self.administrator, reviewed_hash="c" * 64, generation=generation)
        self.assertIn("no-store", response["Cache-Control"])
        self.operation_patch(**create.return_value)
        for _ in range(2):
            progress = self.client.get(response.url)
            self.assertContains(progress, "Backup waiting to start")
            self.assertContains(progress, "does not stop preparation")
            self.assertContains(progress, 'href="' + self.export_url + '"')
        self.assertEqual(create.call_count, 1)

    def test_missing_export_review_never_starts_operation(self):
        create = self.patch("create_export")
        self.native_ready()
        response = self.client.post(self.url, {"action": "export", "scope": "database"})
        self.assertContains(response, "Review the export again", status_code=400)
        create.assert_not_called()

    def test_upload_stages_then_builds_a_server_plan(self):
        self.ready()
        stage = self.patch("stage_import", return_value={"id": self.operation_id, "kind": "import", "status": "staged"})
        plan = self.patch("plan_import", return_value=self.plan)
        self.operation_patch()
        response = self.client.post(self.url, {"action": "upload", "package": SimpleUploadedFile("records.zip", b"synthetic-package", content_type="application/zip")})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(stage.call_args.kwargs, {"actor": self.administrator})
        self.assertEqual(stage.call_args.args[0].name, "records.zip")
        plan.assert_called_once_with(self.operation_id, actor=self.administrator)
        self.assertContains(response, "Choose which user profiles to import")
        self.assertContains(response, "test destination")
        self.assertContains(response, "New accounts are inactive")
        self.assertContains(response, "Import selected users")

    def test_upload_before_maintenance_stages_without_reading_target_records(self):
        self.patch("stage_import", return_value={"id": self.operation_id, "kind": "import", "status": "staged"})
        plan = self.patch("plan_import")
        response = self.client.post(self.url, {"action": "upload", "package": SimpleUploadedFile("records.zip", b"synthetic-package")})
        self.assertEqual(response.status_code, 200)
        plan.assert_not_called()
        self.assertContains(response, "File uploaded. Enable maintenance")
        self.assertContains(response, 'value="plan" disabled')
        self.assertContains(response, f'?operation={self.operation_id}')

    def test_upload_records_file_choice_is_explicit_and_server_validated(self):
        stage = self.patch("stage_import", return_value={
            "id": self.operation_id, "kind": "import", "profile": "application", "status": "staged",
        })
        for value in ("false", "true"):
            with self.subTest(value=value):
                response = self.client.post(self.url, {
                    "action": "upload", "section": "records", "include_files": value,
                    "package": SimpleUploadedFile("records.zip", b"synthetic-package"),
                })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(stage.call_args.kwargs, {
                    "actor": self.administrator, "include_files": value == "true",
                })
        stage.reset_mock()
        invalid = self.client.post(self.url, {
            "action": "upload", "section": "records", "include_files": "unexpected",
            "package": SimpleUploadedFile("records.zip", b"synthetic-package"),
        })
        self.assertContains(invalid, "Select a valid choice", status_code=400)
        stage.assert_not_called()

    def test_old_users_import_bookmark_uses_the_same_package_upload_options(self):
        response = self.client.get(self.url, {"section": "users", "tab": "import"})
        self.assertContains(response, "Choose your backup ZIP")
        self.assertContains(response, 'name="include_files"')
        stage = self.patch("stage_import", return_value={**self.operation, "status": "staged", "plan": None})
        response = self.client.post(self.url, {"section": "users", "action": "upload", "include_files": "true",
            "package": SimpleUploadedFile("records.zip", b"synthetic")})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(stage.call_args.kwargs["include_files"])

    def test_import_review_shows_compatibility_and_missing_files_without_blocking_records(self):
        self.ready()
        plan = {**self.plan, "profile": "application", "include_files": False,
                "compatibility": {"supported": True, "status": "compatible", "message": "Record contract matches.",
                                  "source_release": "3.0.0", "target_release": "3.0.0", "changes": []},
                "file_references": {"total": 5, "included": 0, "not_included": 5,
                                    "missing": 2, "unverified": 1, "remote": 1}}
        self.operation_patch(plan=plan, profile="application")
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(response, "Package compatibility checked")
        self.assertContains(response, "Record contract matches.")
        self.assertContains(response, "Records only")
        self.assertContains(response, "Missing at source")
        self.assertContains(response, "Records keep their file identities")
        self.assertContains(response, 'name="action" value="apply" data-transfer-apply>')
        self.assertEqual(response.context["plan"]["blockers"], [])

    def test_incompatible_import_preserves_original_and_renders_bounded_escaped_differences(self):
        self.ready()
        plan = {**self.plan, "can_apply": False, "blockers": ["A supported record contract is required."],
                "compatibility": {"supported": False, "status": "unsupported",
                                  "message": "No changes were made.", "source_release": "<old>",
                                  "target_release": "3.0.0", "change_count": 1, "changes": [{
                                      "kind": "field_changed", "path": "jobs.<script>alert(1)</script>",
                                      "source": {"data": "x" * 1000}, "target": None,
                                  }]}}
        self.operation_patch(plan=plan, package_sha256="b" * 64)
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(response, "Package is not compatible with this installation")
        self.assertContains(response, "Download original package")
        self.assertContains(response, reverse("admin_data_transfer_download", args=[self.operation_id]))
        self.assertContains(response, "View 1 compatibility difference")
        self.assertContains(response, "jobs.&lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertContains(response, "JSON object")
        self.assertContains(response, "SHA-256")
        self.assertNotContains(response, "<old>")
        self.assertNotContains(response, "x" * 1000)
        self.assertContains(response, 'name="action" value="apply" data-transfer-apply disabled>')

    def test_staged_package_validation_builds_exactly_one_plan_when_ready(self):
        self.ready()
        self.operation_patch(status="staged", plan=None)
        plan = self.patch("plan_import", return_value=self.plan)
        response = self.client.post(self.url, {"action": "plan", "operation_id": self.operation_id})
        self.assertEqual(response.status_code, 200)
        plan.assert_called_once_with(self.operation_id, actor=self.administrator)
        self.assertContains(response, "Destination checked")
        self.assertContains(response, "Choose which user profiles to import")
        self.assertContains(response, "test destination")

    def test_mapping_can_only_reference_server_plan_sources_and_existing_target_accounts(self):
        self.operation_patch()
        plan = self.patch("plan_import", return_value=self.plan)
        response = self.client.post(self.url, {
            "action": "plan", "operation_id": self.operation_id,
            "account_0": str(self.user.pk), "account_999": str(self.other.pk),
            "source_id": "forged-other-account",
        })
        self.assertEqual(response.status_code, 200)
        plan.assert_called_once_with(self.operation_id, actor=self.administrator, expected_plan_hash="a" * 64,
                                     mappings={"source-alice": self.user.pk})

    def test_mapping_pages_preserve_reviewed_identities_outside_the_current_page(self):
        self.plan["account_mappings"] = [
            {"source_id": str(index), "username": f"source-{index}", "target_id": self.other.pk if index == 0 else None}
            for index in range(25)
        ]
        self.operation_patch()
        plan = self.patch("plan_import", return_value=self.plan)
        payload = {"action": "plan", "operation_id": self.operation_id, "mapping_page": "2", "account_0": str(self.user.pk)}
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 200)
        mappings = plan.call_args.kwargs["mappings"]
        self.assertEqual(mappings["0"], self.other.pk)
        self.assertEqual(mappings["20"], self.user.pk)
        self.assertEqual(len(mappings), 25)
        self.assertContains(response, "Accounts 21–25 of 25")
        self.assertNotContains(response, '<label for="id_account_5">')

    def test_nonexistent_target_mapping_is_rejected_without_replanning(self):
        self.operation_patch()
        plan = self.patch("plan_import")
        self.assertEqual(self.client.post(self.url, {
            "action": "plan", "operation_id": self.operation_id, "account_0": "99999999",
        }).status_code, 400)
        plan.assert_not_called()

    def test_apply_requires_exact_destination_and_scope_confirmation(self):
        generation = self.ready()
        self.operation_patch()
        apply = self.patch("start_import")
        payload = {"action": "apply", "operation_id": self.operation_id, "plan_hash": "a" * 64, "generation": generation, "destination_confirmation": "wrong", "confirmed_scope": "on"}
        self.assertContains(self.client.post(self.url, payload), "Enter the destination exactly", status_code=400)
        payload["destination_confirmation"] = "test destination"
        payload.pop("confirmed_scope")
        self.assertEqual(self.client.post(self.url, payload).status_code, 400)
        apply.assert_not_called()

    def test_apply_uses_review_hash_and_service_rejects_a_stale_plan(self):
        generation = self.ready()
        self.operation_patch()
        apply = self.patch("start_import", side_effect=service.TransferError("The target changed. Rebuild the import plan."))
        response = self.client.post(self.url, {
            "action": "apply", "operation_id": self.operation_id, "plan_hash": "d" * 64,
            "generation": generation, "destination_confirmation": "test destination", "confirmed_scope": "on",
        })
        self.assertContains(response, "The target changed", status_code=409)
        apply.assert_called_once_with(self.operation_id, actor=self.administrator, plan_hash="d" * 64, generation=generation, confirmed_scope=True)
        self.assertNotContains(response, "Import started", status_code=409)

    def test_completed_import_does_not_offer_another_apply(self):
        self.operation_patch(status="completed")
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["mapping_form"])
        self.assertIsNone(response.context["resolution_form"])
        self.assertIsNone(response.context["confirmation_form"])
        self.assertNotContains(response, 'value="apply"')
        self.assertNotContains(response, 'value="plan"')

    def test_completed_operation_with_retained_maintenance_pin_offers_finish_recovery(self):
        self.operation_patch(status="completed", maintenance_owned=True, recoverable=True)
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(response, "Finish recovery")
        self.assertNotContains(response, 'value="apply"')
        self.assertNotContains(response, 'value="cancel"')

    def test_import_result_explains_created_records_and_reused_account_identities(self):
        self.operation_patch(status="completed", result={"created_counts": {"accounts": 2}, "created_account_keys": ["new1", "new2"], "user_mappings": {"new1": 5, "new2": 6, "mapped": 7}})
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(response, "2 accounts created.")
        self.assertContains(response, "Verified records")
        self.assertContains(response, "New accounts are inactive")

    def test_status_does_not_expose_private_service_paths(self):
        progress = {"phase": "packaging_files", "label": "Adding selected files to your package.",
                    "processed_items": 2, "total_items": 10, "processed_bytes": 1048576,
                    "total_bytes": 2097152, "updated_at": "2026-10-23T10:00:00+00:00"}
        self.operation_patch(private_path="/private/staging/records.zip", status="running", progress=progress)
        create = self.patch("create_export")
        recover = self.patch("recover_operation")
        response = self.client.get(reverse("admin_data_transfer_status", args=[self.operation_id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "running")
        self.assertEqual(response.json()["progress"], progress)
        self.assertNotIn("private_path", response.json())
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("private", response["Cache-Control"])
        create.assert_not_called()
        recover.assert_not_called()

    def test_running_export_renders_the_saved_stage_and_chunk_progress(self):
        self.operation_patch(kind="export", profile="database", status="running", plan=None, progress={
            "phase": "packaging_files", "label": "Adding selected files to your package.",
            "processed_items": 2, "total_items": 10, "processed_bytes": 1048576,
            "total_bytes": 2097152,
        })
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(response, "Adding selected files to your package.")
        self.assertContains(response, "2 / 10 items")
        self.assertContains(response, 'data-transfer-progress-bytes>1.0\u00a0MB / 2.0\u00a0MB')
        self.assertNotContains(response, "Download database backup")

    def test_download_uses_authorized_open_handle_with_attachment_headers(self):
        download = self.patch("download_operation", return_value=(self.zip_handle(b"zip-bytes"), {"filename": "verified-export.zip"}))
        response = self.client.get(reverse("admin_data_transfer_download", args=[self.operation_id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"zip-bytes")
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="verified-export.zip"')
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Content-Length"], "9")
        self.assertEqual(response["Accept-Ranges"], "bytes")
        download.assert_called_once_with(self.operation_id, actor=self.administrator)

    def test_saved_zip_download_supports_resuming_with_a_verified_etag(self):
        checksum = "f" * 64
        self.patch("download_operation", side_effect=lambda *args, **kwargs: (
            self.zip_handle(b"0123456789"), {"filename": "verified-export.zip", "sha256": checksum},
        ))
        create = self.patch("create_export")
        url = reverse("admin_data_transfer_download", args=[self.operation_id])
        response = self.client.get(url, HTTP_RANGE="bytes=3-6", HTTP_IF_RANGE=f'"sha256-{checksum}"')
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Content-Range"], "bytes 3-6/10")
        self.assertEqual(response["Content-Length"], "4")
        self.assertEqual(b"".join(response.streaming_content), b"3456")
        response = self.client.get(url, HTTP_RANGE="bytes=-3")
        self.assertEqual(response.status_code, 206)
        self.assertEqual(b"".join(response.streaming_content), b"789")
        response = self.client.get(url, HTTP_RANGE="bytes=3-6", HTTP_IF_RANGE='"different-package"')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"0123456789")
        create.assert_not_called()

    def test_saved_zip_head_checks_the_authorized_package_without_sending_or_recreating_it(self):
        handle = self.zip_handle(b"verified-zip")
        download = self.patch("download_operation", return_value=(handle, {"filename": "verified-export.zip"}))
        create = self.patch("create_export")
        url = reverse("admin_data_transfer_download", args=[self.operation_id])
        response = self.client.head(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Length"], "12")
        self.assertEqual(response.content, b"")
        self.assertTrue(handle.closed)
        download.assert_called_once_with(self.operation_id, actor=self.administrator)
        create.assert_not_called()
        self.user.groups.add(Group.objects.get(name=Role.PRODUCT_MANAGER.value))
        self.client.force_login(self.user)
        self.assertEqual(self.client.head(url).status_code, 403)
        self.assertEqual(download.call_count, 1)

    def test_recent_operations_can_be_reopened_without_posting(self):
        service.list_operations.return_value = [{"id": self.operation_id, "kind": "export", "status": "queued"}]
        response = self.client.get(self.url, {"tab": "activity"})
        self.assertContains(response, '<h1>Create a backup</h1>', html=True)
        self.assertContains(response, f'?operation={self.operation_id}')

    def test_completed_export_history_links_to_the_saved_zip_without_running_an_export(self):
        service.list_operations.return_value = [{"id": self.operation_id, "kind": "export", "profile": "database",
                                                "status": "completed", "downloadable": True,
                                                "stored_package_bytes": 2048, "releasable": True}]
        create = self.patch("create_export")
        response = self.client.get(self.url, {"tab": "history"})
        self.assertContains(response, f'href="{reverse("admin_data_transfer_download", args=[self.operation_id])}"')
        self.assertContains(response,
            'href="{}?operation={}#transfer-operation"'.format(
                self.export_url, self.operation_id,
            ),
        )
        self.assertContains(response, ">Download</a>")
        create.assert_not_called()

    def test_retry_is_explicit_and_does_not_start_an_unrelated_operation(self):
        self.operation_patch(status="recovery_required")
        recover = self.patch("recover_operation", return_value={**self.operation, "status": "queued"})
        response = self.client.post(self.url, {"action": "retry", "operation_id": self.operation_id})
        self.assertEqual(response.status_code, 200)
        recover.assert_called_once_with(self.operation_id, actor=self.administrator, action="retry")

    def test_unsupported_methods_are_rejected(self):
        self.assertEqual(self.client.delete(self.url).status_code, 405)
        self.assertEqual(self.client.post(reverse("admin_data_transfer_download", args=[self.operation_id])).status_code, 405)

    def test_tasks_show_only_their_own_controls(self):
        export = self.client.get(self.url, {"tab": "export"})
        self.assertContains(export, 'name="scope"')
        self.assertNotContains(export, 'name="package"')
        imported = self.client.get(self.url, {"tab": "import"})
        self.assertContains(imported, 'name="package"')
        self.assertNotContains(imported, 'name="scope"')
        history = self.client.get(self.url, {"tab": "history"})
        self.assertContains(history, 'name="scope"')
        self.assertNotContains(history, 'name="package"')



    def test_upload_identifies_profile_and_opens_its_matching_section_without_importing(self):
        staged = self.patch("stage_import")
        apply = self.patch("start_import")
        plan = self.patch("plan_import")
        for requested, profile, expected in (
            ("users", "application", "records"),
            ("records", "accounts", "users"),
            ("users", "database", "recovery"),
        ):
            with self.subTest(requested=requested, profile=profile):
                staged.return_value = {"id": self.operation_id, "kind": "import", "status": "staged",
                                       "profile": profile, "downloadable": False, "plan": None}
                response = self.client.post(self.url, {
                    "section": requested, "action": "upload",
                    "package": SimpleUploadedFile("records.zip", b"server-validated-by-mock"),
                })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["transfer_area"], expected)
                self.assertContains(response, "Enable maintenance to check the detected package destination")
        apply.assert_not_called()
        plan.assert_not_called()


    def test_recheck_preserves_server_mappings_without_reposting_dropdowns(self):
        self.operation_patch()
        recheck = self.patch("plan_import", return_value=self.plan)
        response = self.client.post(self.url, {"action": "revalidate", "operation_id": self.operation_id})
        self.assertEqual(response.status_code, 200)
        recheck.assert_called_once_with(self.operation_id, actor=self.administrator)

    def test_save_and_next_saves_current_mapping_before_showing_next_page(self):
        self.plan["account_mappings"] = [
            {"source_id": str(index), "username": f"source-{index}", "target_id": self.other.pk if index == 24 else None}
            for index in range(25)
        ]
        self.operation_patch()
        recheck = self.patch("plan_import", return_value=self.plan)
        response = self.client.post(self.url, {"action": "plan", "operation_id": self.operation_id,
            "mapping_page": 1, "mapping_page_next": 2, "account_0": self.user.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(recheck.call_args.kwargs["mappings"]["0"], self.user.pk)
        self.assertEqual(recheck.call_args.kwargs["mappings"]["24"], self.other.pk)
        self.assertEqual(response.context["mapping_page"].number, 2)

    def test_apply_changed_unsaved_mapping_requires_a_new_review(self):
        self.operation_patch()
        recheck = self.patch("plan_import", return_value=self.plan)
        apply = self.patch("start_import")
        response = self.client.post(self.url, {"action": "apply", "operation_id": self.operation_id,
            "mapping_page": 1, "account_0": self.user.pk,
            "plan_hash": "a" * 64, "generation": 1, "destination_confirmation": "test destination", "confirmed_scope": "on"})
        self.assertEqual(response.status_code, 200)
        recheck.assert_called_once_with(self.operation_id, actor=self.administrator, expected_plan_hash="a" * 64,
                                       mappings={"source-alice": self.user.pk})
        apply.assert_not_called()
        self.assertContains(response, "Account selections changed")

    def test_staged_upload_can_be_discarded_and_active_runner_does_not_offer_recovery(self):
        self.operation_patch(status="staged", plan=None, cancellable=True)
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(response, "Discard package")
        service.get_operation.return_value.update(status="running", cancellable=False, runner_active=True, recoverable=False)
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertNotContains(response, 'value="retry"')
        self.assertContains(response, "data-transfer-status-url")

    def test_application_mapping_offers_only_compatible_username(self):
        match = get_user_model().objects.create_user(username="alice")
        self.plan["profile"] = "application"
        self.operation_patch()
        response = self.client.get(self.url, {"operation": self.operation_id})
        choices = response.context["mapping_form"].fields["account_0"].queryset
        self.assertEqual(list(choices.values_list("pk", flat=True)), [match.pk])

    def account_choice_fixture(self, *, count=1, existing=False):
        """Use the public user-choice plan returned by the transfer service."""
        rows, choices = [], {}
        for index in range(count):
            target = self.user if existing else self.other if count > 20 and index == count - 1 else None
            source_id = str(index + 1)
            disposition = "reuse" if target else "import"
            options = ([{"value": "reuse", "label": "Use existing user without changing it"},
                        {"value": "replace", "label": "Replace name and email only"}]
                       if target else [{"value": "import", "label": "Import as a new inactive user"}])
            options.append({"value": "skip", "label": "Skip incoming user"})
            rows.append({
                "source_id": source_id, "username": target.username if target else f"incoming-{index + 1}",
                "email": "incoming@example.test", "target_id": target.pk if target else None,
                "requires_mapping": False, "blocker": "", "disposition": disposition,
                "choices": options,
                "candidate_targets": ([{"id": target.pk, "username": target.username,
                                       "first_name": target.first_name, "last_name": target.last_name,
                                       "email": target.email}] if target else []),
                "differences": ([{"field": "Email", "current": target.email,
                                  "incoming": "incoming@example.test"}] if target else []),
                "grant_proposals": [], "role_proposals": [],
            })
            choices[source_id] = {"action": disposition, "target_id": target.pk if target else None}
        reused = sum(row["disposition"] == "reuse" for row in rows)
        self.plan.update(profile="accounts", mode="accounts", account_mappings=rows,
                         account_choices=choices,
                         account_summary={"total": count, "selected": count, "create": count - reused,
                                          "reuse": reused, "replace": 0, "skip": 0, "blocked": 0},
                         counts={"accounts": count})
        self.operation.update(profile="accounts")
        return self.operation_patch()

    def account_choice_payload(self, *, action="plan", page=1):
        payload = {"section": "users", "action": action, "operation_id": self.operation_id,
                   "account_choice_page": page, "account_plan_hash": self.plan["plan_hash"]}
        for index, row in enumerate(self.plan["account_mappings"][(page - 1) * 20:page * 20]):
            payload[f"account_action_{index}"] = row["disposition"]
            payload[f"account_target_{index}"] = row["target_id"] or ""
        return payload

    def test_user_import_renders_reviewed_actions_and_summary_without_legacy_mapping_controls(self):
        self.account_choice_fixture(existing=True)
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertEqual(response.context["transfer_area"], "users")
        self.assertEqual(response.context["account_summary"], self.plan["account_summary"])
        self.assertIsNone(response.context["mapping_form"])
        for name in ("account_plan_hash", "account_choice_page", "account_action_0", "account_target_0"):
            self.assertContains(response, f'name="{name}"')
        self.assertNotContains(response, 'name="account_0"')
        self.assertNotContains(response, 'value="overwrite"')
        self.assertContains(response, "Update profile")

    def test_single_existing_user_is_visible_without_a_redundant_target_selector(self):
        self.account_choice_fixture(existing=True)
        response = self.client.get(self.url, {"operation": self.operation_id})
        target = response.context["account_choice_form"]["account_target_0"]
        self.assertTrue(target.is_hidden)
        self.assertEqual(target.value(), self.user.pk)
        self.assertContains(response,
                            f'<input type="hidden" name="account_target_0" value="{self.user.pk}" id="id_account_target_0">',
                            html=True)
        self.assertContains(response,
                            f'<p class="help">Existing user: <strong>{self.user.username}</strong></p>',
                            html=True)
        self.assertNotContains(response, '<select name="account_target_0"')

    def test_unresolved_user_match_hides_confirmation_until_a_reviewed_choice_is_saved(self):
        operation = self.account_choice_fixture(existing=True)
        reason = "username already exists; choose how to handle this user."
        self.plan["account_choices"]["1"] = {"action": "import", "target_id": None}
        self.plan["account_mappings"][0].update(disposition="", target_id=None,
                                               requires_mapping=True, blocker=reason)
        self.plan.update(blockers=["Account selected-account: " + reason], can_apply=False,
                         account_summary={"total": 1, "selected": 1, "create": 0, "reuse": 0,
                                          "replace": 0, "skip": 0, "blocked": 1})
        operation.return_value["plan"] = deepcopy(self.plan)
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertEqual(response.context["account_choice_form"]["account_action_0"].value(), "")
        self.assertEqual(response.context["account_choice_form"]["account_target_0"].value(), self.user.pk)
        self.assertEqual(response.context["account_summary"]["blocked"], 1)
        self.assertContains(response, 'data-transfer-confirmation hidden')
        self.assertNotContains(response, 'data-transfer-update-review hidden')
        self.assertContains(response, reason)
        replan = self.patch("plan_import")
        apply = self.patch("start_import")
        payload = self.account_choice_payload()
        payload["account_target_0"] = self.user.pk
        response = self.client.post(self.url, payload)
        self.assertContains(response, "This field is required", status_code=400)
        replan.assert_not_called()
        apply.assert_not_called()

    def test_saving_user_choice_page_keeps_choices_outside_the_current_page(self):
        self.account_choice_fixture(count=25)
        replan = self.patch("plan_import", return_value=self.plan)
        payload = self.account_choice_payload()
        payload.update(account_action_0="skip", account_choice_page_next=2)
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 200)
        saved = replan.call_args.kwargs["account_choices"]
        self.assertEqual(replan.call_args.kwargs["expected_plan_hash"], "a" * 64)
        self.assertEqual(saved["1"], {"action": "skip", "target_id": None})
        self.assertEqual(saved["25"], {"action": "reuse", "target_id": self.other.pk})
        self.assertEqual(len(saved), 25)
        self.assertEqual(response.context["account_choice_page"].number, 2)
        self.assertEqual(response.context["account_choice_form"]["account_action_4"].value(), "reuse")
        self.assertContains(response, "User choices saved")

    def test_user_choices_reject_stale_review_unoffered_actions_and_targets(self):
        self.account_choice_fixture(existing=True)
        replan = self.patch("plan_import")
        apply = self.patch("start_import")
        original = self.account_choice_payload()
        for changes, message in (
            ({"account_plan_hash": "f" * 64}, "The user review changed"),
            ({"account_action_0": "overwrite"}, "Select a valid choice"),
            ({"account_target_0": self.other.pk}, "Select a valid choice"),
            ({"account_target_0": ""}, "Choose the existing user"),
        ):
            with self.subTest(changes=changes):
                response = self.client.post(self.url, {**original, **changes})
                self.assertContains(response, message, status_code=400)
        replan.assert_not_called()
        apply.assert_not_called()

    def test_user_choices_take_source_identities_and_profile_values_only_from_the_review(self):
        self.account_choice_fixture(existing=True)
        replan = self.patch("plan_import", return_value=self.plan)
        payload = self.account_choice_payload()
        payload.update(account_action_0="replace", source_id="forged-source", account_action_99="replace",
                       account_target_99=self.other.pk, first_name="forged profile value")
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 200)
        replan.assert_called_once_with(self.operation_id, actor=self.administrator,
                                      expected_plan_hash="a" * 64,
                                      account_choices={"1": {"action": "replace", "target_id": self.user.pk}})

    def test_unsaved_user_choices_replan_instead_of_queueing_an_import(self):
        generation = self.ready()
        operation = self.account_choice_fixture(existing=True)
        updated = deepcopy(self.plan)
        updated["plan_hash"] = "c" * 64
        updated["account_choices"]["1"] = {"action": "replace", "target_id": self.user.pk}
        updated["account_mappings"][0]["disposition"] = "replace"

        def save_review(*_args, **_kwargs):
            operation.return_value["plan"] = updated
            return updated

        replan = self.patch("plan_import", side_effect=save_review)
        apply = self.patch("start_import")
        payload = self.account_choice_payload(action="apply")
        payload.update(account_action_0="replace", plan_hash="a" * 64, generation=generation,
                       destination_confirmation="test destination", confirmed_scope="on")
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 200)
        replan.assert_called_once_with(self.operation_id, actor=self.administrator,
                                      expected_plan_hash="a" * 64,
                                      account_choices=updated["account_choices"])
        apply.assert_not_called()
        self.assertEqual(response.context["plan"]["plan_hash"], "c" * 64)
        self.assertContains(response, "Account selections changed")

    def test_unchanged_user_choices_reach_the_reviewed_import_service(self):
        generation = self.ready()
        self.account_choice_fixture(existing=True)
        replan = self.patch("plan_import")
        apply = self.patch("start_import", return_value={**self.operation, "status": "queued"})
        payload = self.account_choice_payload(action="apply")
        payload.update(plan_hash="a" * 64, generation=generation,
                       destination_confirmation="test destination", confirmed_scope="on")
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 200)
        replan.assert_not_called()
        apply.assert_called_once_with(self.operation_id, actor=self.administrator,
                                     plan_hash="a" * 64, generation=generation, confirmed_scope=True)

    def incompatible_schema(self):
        return self.patch("schema_readiness", return_value={
            "ready": False,
            "message": "Current model schema is not ready: missing table qc_database_transfer_receipt. Inspection made no changes.",
        })

    def test_unified_export_uses_native_availability_even_when_model_schema_is_incompatible(self):
        self.ready()
        self.incompatible_schema()
        response = self.client.get(self.url, {"tab": "export"})
        self.assertContains(response, "Full database backups require PostgreSQL")
        self.assertNotContains(response, "Record transfers are unavailable")
        self.assertContains(response, 'value="preview_export" disabled')
        imported = self.client.get(self.url, {"tab": "import"})
        self.assertContains(imported, 'value="upload" disabled')

    def test_unavailable_database_blocks_export_and_incompatible_target_blocks_upload(self):
        self.incompatible_schema()
        preview = self.patch("export_preview")
        stage = self.patch("stage_import")
        response = self.client.post(self.url, {"action": "preview_export", "scope": "database"})
        self.assertContains(response, "Full database backups require PostgreSQL", status_code=409)
        response = self.client.post(self.url, {"action": "upload", "package": SimpleUploadedFile("records.zip", b"synthetic")})
        self.assertContains(response, "missing table qc_database_transfer_receipt", status_code=409)
        preview.assert_not_called()
        stage.assert_not_called()

    def test_schema_mismatch_preserves_history_download_and_discard(self):
        self.incompatible_schema()
        self.assertContains(self.client.get(self.url, {"tab": "history"}), '<h1>Create a backup</h1>', html=True)
        self.operation_patch(status="staged", plan=None, cancellable=True)
        recover = self.patch("recover_operation", return_value={**self.operation, "status": "cancelled"})
        response = self.client.post(self.url, {"action": "cancel", "operation_id": self.operation_id})
        self.assertContains(response, "Transfer cancelled.")
        recover.assert_called_once_with(self.operation_id, actor=self.administrator, action="cancel")
        download = self.patch("download_operation", return_value=(self.zip_handle(b"zip"), {"filename": "export.zip"}))
        response = self.client.get(reverse("admin_data_transfer_download", args=[self.operation_id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"zip")
        download.assert_called_once()

    def native_ready(self, *, can_create=True):
        self.database_availability.return_value = {
            "ready": True, "message": ("PostgreSQL backup tools are ready." if can_create else
                "PostgreSQL permissions do not allow creating a restore database. An operator must enable database creation for this installation."),
            "restore_reason": "" if can_create else "PostgreSQL permissions do not allow creating a restore database. An operator must enable database creation for this installation.",
            "can_create_restore_database": can_create, "current_database": "qc_tool_live",
        }

    def native_plan(self):
        self.native_ready()
        self.plan.update(profile="database", target_label="postgresql / qc_tool_restore",
                         confirmation_text="postgresql / qc_tool_restore", counts={"tables": 20},
                         account_mappings=[])
        self.operation.update(profile="database", destination={"database": "qc_tool_restore"})
        return self.operation_patch()

    def test_export_explains_sensitive_contents_and_manual_metadata_recovery(self):
        response = self.client.get(self.url, {"tab": "export"})
        for text in ("password hashes", "credentials", "manual recovery", "Store the ZIP securely"):
            self.assertContains(response, text)
        self.assertNotContains(response, "Passwords and access credentials are excluded")

    def test_full_backup_preview_is_available_without_current_model_schema(self):
        self.ready()
        self.native_ready()
        self.incompatible_schema()
        preview = self.patch("export_preview", return_value={
            "review_hash": "c" * 64, "profile": "database", "counts": {"tables": 20},
        })
        response = self.client.post(self.url, {"action": "preview_export", "scope": "database", "users": "invalid-ignored-id"})
        self.assertEqual(response.status_code, 200)
        preview.assert_called_once_with({"profile": "database", "user_ids": [], "components": []}, actor=self.administrator)
        self.assertTrue(response.context["transfers_ready"])
        self.assertContains(response, "Create backup ZIP")
        self.assertNotContains(response, "Passwords, access tokens, sessions and service credentials are excluded")
        self.assertNotContains(response, 'name="users"')

    def test_full_backup_creation_preserves_exact_review_and_generation(self):
        generation = self.ready()
        self.native_ready()
        self.incompatible_schema()
        create = self.patch("create_export", return_value={
            "id": self.operation_id, "kind": "export", "profile": "database", "status": "queued",
        })
        response = self.client.post(self.url, {
            "action": "export", "scope": "database", "reviewed_hash": "c" * 64,
            "generation": generation, "users": self.user.pk,
        })
        self.assertRedirects(response, f"{self.export_url}?operation={self.operation_id}#transfer-operation",
                             status_code=303, fetch_redirect_response=False)
        create.assert_called_once_with({"profile": "database", "user_ids": [], "components": []}, actor=self.administrator,
                                       reviewed_hash="c" * 64, generation=generation)

    def test_unavailable_native_tools_block_exports_but_not_older_package_uploads(self):
        preview = self.patch("export_preview")
        response = self.client.post(self.url, {"action": "preview_export", "scope": "database"})
        self.assertContains(response, "Full database backups require PostgreSQL", status_code=409)
        preview.assert_not_called()
        upload = self.client.get(self.url, {"tab": "import"})
        self.assertContains(upload, 'value="upload">')

    def test_native_restore_review_has_no_account_mapping_and_requires_trusted_source(self):
        self.ready()
        self.incompatible_schema()
        self.native_plan()
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(response, "<h2>Check what will be restored and where</h2>", html=True)
        self.assertContains(response, "postgresql / qc_tool_restore")
        self.assertContains(response, "I trust the source of this database backup")
        self.assertContains(response, "live database stays unchanged")
        self.assertContains(response, "Restore database")
        self.assertContains(response, '<input type="hidden" name="destination_confirmation" value="postgresql / qc_tool_restore"')
        self.assertNotContains(response, "Type postgresql / qc_tool_restore")
        self.assertNotContains(response, "Choose account identities")
        self.assertNotContains(response, "New accounts are inactive")
        self.assertIsNone(response.context["mapping_form"])
        self.assertTrue(response.context["transfers_ready"])

    def test_native_restore_requires_exact_destination_and_trusted_source_even_without_js(self):
        generation = self.ready()
        self.native_plan()
        apply = self.patch("start_import", return_value={**self.operation, "status": "queued"})
        payload = {"action": "apply", "operation_id": self.operation_id, "plan_hash": "a" * 64,
                   "generation": generation, "destination_confirmation": "postgresql / qc_tool_restore"}
        self.assertEqual(self.client.post(self.url, payload).status_code, 400)
        apply.assert_not_called()
        payload.update(confirmed_scope="on", destination_confirmation="live database")
        self.assertEqual(self.client.post(self.url, payload).status_code, 400)
        apply.assert_not_called()
        payload.update(destination_confirmation="postgresql / qc_tool_restore", mapping_page=1, account_0=self.user.pk)
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 200)
        apply.assert_called_once_with(self.operation_id, actor=self.administrator, plan_hash="a" * 64,
                                      generation=generation, confirmed_scope=True)

    def test_native_package_can_be_staged_before_maintenance_or_database_creation_privileges(self):
        self.native_ready(can_create=False)
        stage = self.patch("stage_import", return_value={
            "id": self.operation_id, "kind": "import", "profile": "database", "status": "staged",
        })
        plan = self.patch("plan_import")
        response = self.client.post(self.url, {"action": "upload", "package": SimpleUploadedFile("backup.zip", b"native-zip")})
        self.assertEqual(response.status_code, 200)
        stage.assert_called_once()
        plan.assert_not_called()
        self.assertContains(response, "Create restore database")
        self.assertContains(response, "An operator must enable database creation")
        self.assertContains(response, 'value="prepare_destination" disabled')
        self.assertNotContains(response, "QC_TOOL_RESTORE_DATABASE")

    def test_pending_native_plan_offers_destination_preparation_without_restore_fields(self):
        self.ready()
        self.native_plan()
        operation = service.get_operation.return_value
        operation.pop("destination")
        operation["plan"].update(target_label="", confirmation_text="", can_apply=False,
                                 blockers=["Prepare a destination first."])
        prepare = self.patch("prepare_restore_destination", create=True)
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(response, "Create restore database")
        self.assertContains(response, "Your active database stays in use")
        self.assertNotContains(response, 'value="apply"')
        self.assertNotContains(response, 'name="destination_confirmation"')
        prepare.assert_not_called()

    def test_explicit_prepare_uses_server_operation_and_rereads_exact_destination(self):
        self.ready()
        self.native_plan()
        prepared = deepcopy(service.get_operation.return_value)
        pending = deepcopy(prepared)
        pending.pop("destination")
        pending["plan"].update(target_label="", confirmation_text="", can_apply=False)
        service.get_operation.side_effect = (pending, prepared)
        prepare = self.patch("prepare_restore_destination", create=True)
        response = self.client.post(self.url, {
            "action": "prepare_destination", "operation_id": self.operation_id,
            "database": "qc_tool_live", "host": "untrusted.example", "password": "never-used",
        })
        self.assertEqual(response.status_code, 200)
        prepare.assert_called_once_with(self.operation_id, actor=self.administrator)
        self.assertContains(response, "Fresh destination prepared")
        self.assertContains(response, "<h2>Check what will be restored and where</h2>", html=True)
        self.assertContains(response, "postgresql / qc_tool_restore")
        self.assertNotContains(response, 'value="prepare_destination"')
        self.assertNotContains(response, "never-used")

    def test_ready_upload_checks_backup_without_creating_a_destination(self):
        self.ready()
        self.native_plan()
        pending = service.get_operation.return_value
        pending.pop("destination")
        pending["plan"].update(target_label="", confirmation_text="", can_apply=False)
        stage = self.patch("stage_import", return_value={**pending, "status": "staged", "plan": None})
        plan = self.patch("plan_import", return_value=pending["plan"])
        prepare = self.patch("prepare_restore_destination", create=True)
        response = self.client.post(self.url, {
            "action": "upload", "package": SimpleUploadedFile("backup.zip", b"native-zip"),
        })
        self.assertContains(response, "Create restore database")
        self.assertNotContains(response, 'value="apply"')
        stage.assert_called_once()
        plan.assert_called_once_with(self.operation_id, actor=self.administrator)
        prepare.assert_not_called()

    def test_missing_create_privilege_blocks_preparation_but_not_existing_destination_restore(self):
        self.ready()
        self.native_plan()
        prepared = deepcopy(service.get_operation.return_value)
        pending = service.get_operation.return_value
        pending.pop("destination")
        self.native_ready(can_create=False)
        prepare = self.patch("prepare_restore_destination", create=True)
        response = self.client.post(self.url, {"action": "prepare_destination", "operation_id": self.operation_id})
        self.assertContains(response, "An operator must enable database creation", status_code=409)
        prepare.assert_not_called()
        service.get_operation.return_value = prepared
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertTrue(response.context["transfers_ready"])
        self.assertContains(response, "Restore database")

    def test_destination_preparation_requires_csrf_and_native_import_profile(self):
        self.ready()
        self.native_plan()
        service.get_operation.return_value.pop("destination")
        prepare = self.patch("prepare_restore_destination", create=True)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.administrator)
        self.assertEqual(client.post(self.url, {"action": "prepare_destination", "operation_id": self.operation_id}).status_code, 403)
        service.get_operation.return_value.update(profile="accounts")
        service.get_operation.return_value["plan"]["profile"] = "accounts"
        response = self.client.post(self.url, {"action": "prepare_destination", "operation_id": self.operation_id})
        self.assertContains(response, "Choose an uploaded full database backup", status_code=409)
        prepare.assert_not_called()

    def test_native_completion_and_history_explain_separate_restore(self):
        self.native_plan()
        service.get_operation.return_value.update(status="completed", result={
            "target_label": "postgresql / qc_tool_restore", "counts": {"tables": 20}, "verified": True,
        })
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(response, "Your restored database is ready to review")
        self.assertContains(response, "QC Tool still uses the active database named above")
        self.assertContains(response, "File contents were not copied.")
        self.assertContains(response, "Deployment secrets require separate recovery.")
        self.assertNotContains(response, "accounts created")
        service.list_operations.return_value = [{**self.operation, "profile": "database"}]
        history = self.client.get(self.import_url)
        self.assertContains(history, "Import tasks")
        self.assertContains(history, self.operation_id)

    def test_completed_native_history_stays_readable_without_maintenance_or_switch_review(self):
        self.native_plan()
        service.get_operation.return_value.update(status="completed", result={"target_database": "qc_tool_restore", "verified": True})
        service.activation_preview.side_effect = service.TransferError("Maintenance must be ready for a switch review.")
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(response, "Your restored database is ready to review")
        self.assertContains(response, "Enable maintenance to review and switch")
        self.assertNotContains(response, "Use this database")
        service.activation_preview.assert_not_called()
        self.control_state["active_database"] = "qc_tool_restore"
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(response, "This restored database is now active")
        self.assertNotContains(response, "The live database has not been replaced")
        self.assertNotContains(response, "Maintenance remains on")

    def test_native_source_details_are_allowlisted_and_html_escaped(self):
        self.native_plan()
        service.get_operation.return_value["plan"]["source_details"] = {
            "app_version": "3.0.0", "postgresql_version": "14", "source_database": "<source>",
            "password": "never-display-this", "dsn": "private-dsn",
        }
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(response, "&lt;source&gt;")
        self.assertNotContains(response, "never-display-this")
        self.assertNotContains(response, "private-dsn")

    def activation_fixture(self, *, requires_credentials=False):
        generation = self.ready()
        self.native_plan()
        service.get_operation.return_value.update(status="completed", result={"target_label": "qc_tool_restore", "verified": True})
        self.activation_review.update(can_apply=True, requires_credentials=requires_credentials)
        return {
            "action": "activate_database", "operation_id": self.operation_id,
            "activation-review_hash": "e" * 64, "activation-generation": generation,
            "activation-revision": 0, "activation-destination_confirmation": "qc_tool_restore",
            "activation-confirmed_storage": "on",
        }

    def test_completed_native_restore_requires_explicit_review_before_showing_switch_form(self):
        self.activation_fixture()
        activate = self.patch("activate_database", create=True)
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertTrue(response.context["can_review_database_switch"])
        self.assertIsNone(response.context["activation_form"])
        self.assertContains(response, 'value="review_database_switch"')
        self.assertNotContains(response, 'name="activation-destination_confirmation"')
        self.assertNotContains(response, 'name="activation-password"')
        service.activation_preview.assert_not_called()
        activate.assert_not_called()

        response = self.client.post(self.url, {"action": "review_database_switch", "operation_id": self.operation_id})
        self.assertEqual(response.status_code, 200)
        service.activation_preview.assert_called_once_with(self.operation_id, actor=self.administrator)
        self.assertIsNotNone(response.context["activation_form"])
        self.assertContains(response, "Use this database")
        self.assertContains(response, "matching files and administrator access")
        activate.assert_not_called()

    def test_removed_database_copy_retains_history_without_offering_switch(self):
        self.activation_fixture()
        for field, label in (("database_deletion_requested_at", "Database removal pending"),
                             ("database_deleted_at", "Database copy deleted")):
            with self.subTest(field=field):
                service.get_operation.return_value[field] = "2026-10-23T10:00:00Z"
                response = self.client.get(self.url, {"operation": self.operation_id})
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.context["can_review_database_switch"])
                self.assertNotContains(response, 'value="review_database_switch"')
                self.assertContains(response, label)
                if field == "database_deletion_requested_at":
                    self.assertContains(response, 'href="' + self.url + '?tab=databases"')
                service.get_operation.return_value.pop(field)

    def test_unverified_native_result_does_not_claim_a_selectable_complete_restore(self):
        self.activation_fixture()
        service.get_operation.return_value["result"]["verified"] = False
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertFalse(response.context["can_review_database_switch"])
        self.assertContains(response, "The restore needs verification")
        self.assertNotContains(response, "This restored database is now active")

    def test_explicit_switch_review_displays_blockers_without_enabling_the_switch(self):
        self.activation_fixture()
        self.activation_review.update(can_apply=False, blockers=["The restored schema must be checked."])
        activate = self.patch("activate_database", create=True)
        response = self.client.post(self.url, {"action": "review_database_switch", "operation_id": self.operation_id})
        self.assertEqual(response.status_code, 200)
        service.activation_preview.assert_called_once_with(self.operation_id, actor=self.administrator)
        self.assertContains(response, "The restored schema must be checked.")
        self.assertContains(response, '<fieldset disabled>')
        self.assertNotContains(response, 'value="review_database_switch"')
        activate.assert_not_called()

    def test_switch_review_rejects_noncompleted_or_non_native_operations(self):
        self.activation_fixture()
        operation = service.get_operation.return_value
        for kind, profile, status in (
            ("export", "database", "completed"),
            ("import", "application", "completed"),
            ("import", "database", "planned"),
            ("import", "database", "running"),
        ):
            with self.subTest(kind=kind, profile=profile, status=status):
                operation.update(kind=kind, profile=profile, status=status, plan=None)
                response = self.client.post(self.url, {
                    "action": "review_database_switch", "operation_id": self.operation_id,
                })
                self.assertEqual(response.status_code, 409)
                self.assertIsNone(response.context["activation_form"])
        service.activation_preview.assert_not_called()

    def test_switch_review_requires_maintenance_readiness(self):
        self.activation_fixture()
        for phase in ("off", "quiescing"):
            with self.subTest(phase=phase), patch(
                "qc_tool.frontend.dashboard.views.admin_data_transfer.maintenance.read_status",
                return_value={"phase": phase, "enabled": phase != "off", "generation": 1},
            ):
                response = self.client.post(self.url, {
                    "action": "review_database_switch", "operation_id": self.operation_id,
                })
                self.assertEqual(response.status_code, 409)
                self.assertFalse(response.context["can_review_database_switch"])
                self.assertIsNone(response.context["activation_form"])
        service.activation_preview.assert_not_called()

    def test_switch_review_keeps_csrf_and_administrator_permissions(self):
        self.activation_fixture()
        payload = {"action": "review_database_switch", "operation_id": self.operation_id}
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.administrator)
        self.assertEqual(client.post(self.url, payload).status_code, 403)
        self.user.groups.add(Group.objects.get(name=Role.PRODUCT_MANAGER.value))
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(self.url, payload).status_code, 403)
        service.activation_preview.assert_not_called()

    def test_switch_passes_review_revision_exact_destination_and_storage_confirmation(self):
        payload = self.activation_fixture()

        def switch(*args, **kwargs):
            self.control_state.update(active_database="qc_tool_restore", previous_database="qc_tool_live",
                                      revision=1, has_selection=True)

        activate = self.patch("activate_database", create=True, side_effect=switch)
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 200)
        service.activation_preview.assert_called_once_with(self.operation_id, actor=self.administrator)
        activate.assert_called_once_with(self.operation_id, actor=self.administrator, review_hash="e" * 64,
            generation=payload["activation-generation"], revision=0, destination_confirmation="qc_tool_restore",
            confirmed_storage=True, username="", password="")
        self.assertContains(response, "This restored database is now active")
        self.assertContains(response, "Switch back to qc_tool_live")
        self.assertNotContains(response, "Use this database")

    def test_switch_requires_exact_target_storage_confirmation_and_fresh_review(self):
        payload = self.activation_fixture()
        activate = self.patch("activate_database", create=True)
        payload.pop("activation-confirmed_storage")
        self.assertEqual(self.client.post(self.url, payload).status_code, 400)
        payload.update({"activation-confirmed_storage": "on", "activation-destination_confirmation": "qc_tool_live"})
        self.assertEqual(self.client.post(self.url, payload).status_code, 400)
        activate.assert_not_called()
        payload["activation-destination_confirmation"] = "qc_tool_restore"
        activate.side_effect = service.TransferError("The database review changed. Review it again.")
        self.assertContains(self.client.post(self.url, payload), "database review changed", status_code=409)

    def test_target_administrator_password_is_required_when_needed_and_never_redisplayed(self):
        payload = self.activation_fixture(requires_credentials=True)
        activate = self.patch("activate_database", create=True)
        self.assertEqual(self.client.post(self.url, payload).status_code, 400)
        activate.assert_not_called()
        password = " keep-this-secret-with-spaces "
        payload.update({"activation-username": "restored-admin", "activation-password": password})
        activate.side_effect = service.TransferError("Destination administrator credentials could not be verified.")
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 409)
        self.assertNotContains(response, password, status_code=409)
        self.assertEqual(activate.call_args.kwargs["password"], password)
        self.assertContains(response, 'name="activation-password"', status_code=409)

    def test_database_switch_requires_a_completed_native_import(self):
        payload = self.activation_fixture()
        service.get_operation.return_value["status"] = "planned"
        activate = self.patch("activate_database", create=True)
        self.assertContains(self.client.post(self.url, payload), "Complete and verify a full database restore", status_code=409)
        activate.assert_not_called()

    def test_previous_database_control_remains_available_in_import_without_an_operation(self):
        self.ready()
        self.control_state.update(previous_database="qc_tool_previous", revision=4, has_selection=True)
        rollback = self.patch("rollback_database", create=True)
        response = self.client.get(self.import_url)
        self.assertContains(response, "Switch back to qc_tool_previous")
        self.assertContains(response, 'value="rollback_database"')
        self.assertNotContains(response, 'name="operation_id"')
        rollback.assert_not_called()

    def test_switch_back_uses_exact_retained_database_and_revision(self):
        generation = self.ready()
        self.control_state.update(previous_database="qc_tool_previous", revision=4, has_selection=True)
        rollback = self.patch("rollback_database", create=True)
        response = self.client.post(self.url, {
            "action": "rollback_database", "rollback-generation": generation, "rollback-revision": 4,
            "rollback-destination_confirmation": "qc_tool_previous", "rollback-confirmed_storage": "on",
        })
        self.assertEqual(response.status_code, 200)
        rollback.assert_called_once_with(actor=self.administrator, generation=generation, revision=4,
            destination_confirmation="qc_tool_previous", confirmed_storage=True, username="", password="")
        self.assertContains(response, "Switched back to the previous database")

    def test_switch_back_requires_a_known_previous_database_and_storage_acknowledgment(self):
        generation = self.ready()
        rollback = self.patch("rollback_database", create=True)
        payload = {"action": "rollback_database", "rollback-generation": generation, "rollback-revision": 0,
                   "rollback-destination_confirmation": "unrelated_database", "rollback-confirmed_storage": "on"}
        self.assertEqual(self.client.post(self.url, payload).status_code, 400)
        self.control_state.update(previous_database="qc_tool_previous")
        payload.update({"rollback-destination_confirmation": "qc_tool_previous"})
        payload.pop("rollback-confirmed_storage")
        self.assertEqual(self.client.post(self.url, payload).status_code, 400)
        rollback.assert_not_called()

    def test_switch_and_switch_back_keep_csrf_and_administrator_permissions(self):
        payload = self.activation_fixture()
        activate = self.patch("activate_database", create=True)
        rollback = self.patch("rollback_database", create=True)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.administrator)
        self.assertEqual(client.post(self.url, payload).status_code, 403)
        self.assertEqual(client.post(self.url, {"action": "rollback_database"}).status_code, 403)
        self.user.is_staff = True
        self.user.save(update_fields=("is_staff",))
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(self.url, payload).status_code, 403)
        self.assertEqual(self.client.post(self.url, {"action": "rollback_database"}).status_code, 403)
        activate.assert_not_called()
        rollback.assert_not_called()

    def test_database_switch_promotes_session_without_sql_writes_and_keeps_its_origin(self):
        payload = self.activation_fixture()
        original_session = self.client.session.session_key

        def activate(*args, **kwargs):
            self.assertTrue(promote.called)
            self.control_state.update(active_database="qc_tool_restore", previous_database="qc_tool_live", revision=1)

        self.patch("activate_database", create=True, side_effect=activate)
        self.patch("rollback_database", create=True)
        with patch("qc_tool.frontend.dashboard.views.admin_data_transfer.login_without_database_writes",
                   wraps=login_without_database_writes) as promote:
            with CaptureQueriesContext(connection) as queries:
                response = self.client.post(self.url, payload)
            self.assertEqual(response.status_code, 200)
            mutations = [item["sql"] for item in queries
                         if item["sql"].lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE "))]
            self.assertEqual(mutations, [])
            signed = cookie_session(self.client.cookies[settings.SESSION_COOKIE_NAME].value)
            self.assertIsNotNone(signed)
            self.assertEqual(signed.get(ORIGIN_DATABASE), connection.settings_dict["NAME"])
            self.assertTrue(Session.objects.filter(session_key=original_session).exists())
            self.assertEqual(self.client.post(self.url, {
                "action": "rollback_database", "rollback-generation": payload["activation-generation"],
                "rollback-revision": 1, "rollback-destination_confirmation": "qc_tool_live",
                "rollback-confirmed_storage": "on",
            }).status_code, 200)
            promote.assert_called_once()

    def additive_fixture(self, conflict_count=1):
        generation = self.ready()
        self.plan.update(
            profile="application", mode="additive", account_mappings=[], resolutions={},
            resource_summary=[{"resource": "deliveries", "label": "Deliveries", "create": 12,
                               "reuse": 3, "skip": 1, "blocked": 1}],
            record_conflicts=[{
                "key": f"deliveries:{index}", "resource": "deliveries", "label": f"Delivery {index}.zip",
                "reason": "A delivery identity already exists with different evidence.",
                "differences": [{"field": "Description", "current": "Existing description", "incoming": "Incoming description"}],
                "choices": [{"value": "skip", "label": "Skip incoming record and dependent history"},
                            {"value": "reuse", "label": "Use existing record without changing it"}],
                "resolution": None, "impact": {"deliveries": 1, "jobs": 3},
            } for index in range(conflict_count)],
        )
        self.operation.update(profile="application")
        self.operation_patch()
        return generation

    def test_additive_review_compares_records_and_counts_without_overwrite_controls(self):
        self.additive_fixture()
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(response, "Check which records will be added")
        self.assertContains(response, "Existing QC records are kept unchanged")
        self.assertContains(response, "What will change")
        self.assertContains(response, "Already present")
        self.assertContains(response, "Existing description")
        self.assertContains(response, "Incoming description")
        self.assertContains(response, "Skipping affects incoming records")
        self.assertContains(response, 'name="resolution_0"')
        self.assertNotContains(response, "Requires empty QC business tables")
        self.assertNotContains(response, 'value="overwrite"')

    def test_blocked_import_hides_confirmation_and_offers_one_review_action(self):
        self.additive_fixture()
        self.plan.update(can_apply=False, blockers=["Resolve the delivery identity before importing."])
        self.operation_patch()
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(response, 'data-transfer-confirmation hidden')
        self.assertContains(response, 'data-transfer-apply disabled')
        self.assertContains(response, 'data-transfer-update-review', count=1)
        self.assertNotContains(response, 'data-transfer-update-review hidden')
        self.assertContains(response, 'value="plan" formnovalidate', count=1)
        self.assertContains(response, '<input type="hidden" name="action" value="plan">', html=True)
        self.assertNotContains(response, '<noscript><button')

    def test_valid_review_hides_the_update_action_and_keeps_a_no_javascript_save(self):
        self.additive_fixture()
        self.plan.update(can_apply=True, blockers=[], resolutions={"deliveries:0": "reuse"})
        self.plan["record_conflicts"][0]["resolution"] = "reuse"
        self.operation_patch()
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(response, 'data-transfer-update-review hidden', count=1)
        self.assertNotContains(response, 'data-transfer-confirmation hidden')
        self.assertNotContains(response, 'data-transfer-apply disabled')
        self.assertContains(response, (
            '<noscript><button type="submit" class="button btn-qc-secondary" name="action" value="plan" '
            'formnovalidate>Save choices and review</button></noscript>'
        ), html=True)

    def test_unavailable_delivery_files_keep_their_specific_review_states(self):
        self.additive_fixture()
        self.plan.update(can_apply=False, blockers=["Original delivery inputs require review."], delivery_files=[
            {"filename": "missing.zip", "status": "missing", "job_count": 1,
             "message": "The original ZIP is unavailable."},
            {"filename": "different.zip", "status": "different", "job_count": 2,
             "message": "The server file does not match this delivery."},
            {"filename": "unverified.zip", "status": "unverified_history", "job_count": 3,
             "message": "The historical input checksum is missing."},
        ])
        self.operation_patch()
        response = self.client.get(self.url, {"operation": self.operation_id})
        for label in ("Missing file", "Different file on server", "Historical job input not verified"):
            self.assertContains(response, f"<strong>{label}</strong>", html=True)
        for row in self.plan["delivery_files"]:
            self.assertContains(response, row["filename"])
            self.assertContains(response, row["message"])
        table = response.content.decode().split('<table class="transfer-files">', 1)[1].split('</table>', 1)[0]
        self.assertNotIn("Verified file details", table)
        self.assertNotIn("Already on server — verified", table)
        self.assertContains(response, 'data-transfer-confirmation hidden')

    def test_resolution_choices_use_only_server_reviewed_source_keys(self):
        self.additive_fixture()
        replan = self.patch("plan_import", return_value=self.plan)
        response = self.client.post(self.url, {
            "action": "resolve_conflicts", "operation_id": self.operation_id, "conflict_page": 1,
            "resolution_plan_hash": "a" * 64, "resolution_0": "skip",
            "source_key": "jobs:untrusted", "target_id": "9999", "resolution_99": "reuse",
        })
        self.assertContains(response, "Import choices saved")
        replan.assert_called_once_with(self.operation_id, actor=self.administrator,
                                      expected_plan_hash="a" * 64,
                                      resolutions={"deliveries:0": "skip"})

    def test_resolution_rejects_unoffered_choice_and_stale_review(self):
        self.additive_fixture()
        replan = self.patch("plan_import")
        payload = {"action": "resolve_conflicts", "operation_id": self.operation_id, "conflict_page": 1,
                   "resolution_plan_hash": "a" * 64, "resolution_0": "overwrite"}
        self.assertContains(self.client.post(self.url, payload), "Select a valid choice", status_code=400)
        payload.update(resolution_0="skip", resolution_plan_hash="f" * 64)
        self.assertContains(self.client.post(self.url, payload), "The import review changed", status_code=400)
        replan.assert_not_called()

    def test_resolution_pagination_preserves_saved_choices_outside_current_page(self):
        self.additive_fixture(25)
        self.plan["resolutions"] = {"deliveries:0": "reuse", "units:hidden": "skip"}
        self.operation_patch()
        replan = self.patch("plan_import", return_value=self.plan)
        response = self.client.post(self.url, {
            "action": "resolve_conflicts", "operation_id": self.operation_id, "conflict_page": 2,
            "resolution_plan_hash": "a" * 64, "resolution_0": "skip",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(replan.call_args.kwargs["resolutions"],
                         {"deliveries:0": "reuse", "units:hidden": "skip", "deliveries:20": "skip"})
        self.assertEqual(response.context["conflict_page"].number, 2)

    def test_saved_resolution_can_be_cleared_for_another_review(self):
        self.additive_fixture()
        self.plan["resolutions"] = {"deliveries:0": "skip", "units:hidden": "reuse"}
        self.plan["record_conflicts"][0]["resolution"] = "skip"
        self.operation_patch()
        replan = self.patch("plan_import", return_value=self.plan)
        self.client.post(self.url, {"action": "resolve_conflicts", "operation_id": self.operation_id,
            "conflict_page": 1, "resolution_plan_hash": "a" * 64, "resolution_0": ""})
        self.assertEqual(replan.call_args.kwargs["resolutions"], {"units:hidden": "reuse"})

    def test_unsaved_resolution_changes_replan_instead_of_starting_import(self):
        generation = self.additive_fixture()
        replan = self.patch("plan_import", return_value=self.plan)
        start = self.patch("start_import")
        response = self.client.post(self.url, {
            "action": "apply", "operation_id": self.operation_id, "conflict_page": 1,
            "resolution_plan_hash": "a" * 64, "resolution_0": "skip", "plan_hash": "a" * 64,
            "generation": generation, "destination_confirmation": "test destination", "confirmed_scope": "on",
        })
        self.assertContains(response, "Import choices changed. Review and confirm")
        replan.assert_called_once_with(self.operation_id, actor=self.administrator,
                                      expected_plan_hash="a" * 64,
                                      resolutions={"deliveries:0": "skip"})
        start.assert_not_called()

    def test_unchanged_resolution_reaches_existing_reviewed_import_service(self):
        generation = self.additive_fixture()
        self.plan["resolutions"] = {"deliveries:0": "reuse"}
        self.plan["record_conflicts"][0]["resolution"] = "reuse"
        self.operation_patch()
        replan = self.patch("plan_import")
        start = self.patch("start_import", return_value={**self.operation, "status": "queued"})
        response = self.client.post(self.url, {
            "action": "apply", "operation_id": self.operation_id, "conflict_page": 1,
            "resolution_plan_hash": "a" * 64, "resolution_0": "reuse", "plan_hash": "a" * 64,
            "generation": generation, "destination_confirmation": "test destination", "confirmed_scope": "on",
        })
        self.assertEqual(response.status_code, 200)
        replan.assert_not_called()
        start.assert_called_once_with(self.operation_id, actor=self.administrator, plan_hash="a" * 64,
                                      generation=generation, confirmed_scope=True)

    def test_resolution_cannot_be_applied_to_native_database_backup(self):
        self.ready()
        self.database_availability.return_value["ready"] = True
        self.native_plan()
        self.operation_patch()
        replan = self.patch("plan_import")
        response = self.client.post(self.url, {"action": "resolve_conflicts", "operation_id": self.operation_id,
            "conflict_page": 1, "resolution_plan_hash": "a" * 64, "resolution_0": "skip"})
        self.assertContains(response, "only for additive QC record imports", status_code=409)
        replan.assert_not_called()

    def test_review_shows_verified_retained_zip_evidence_and_escapes_package_text(self):
        self.additive_fixture()
        self.plan["delivery_files"] = [{"filename": "<script>unsafe.zip</script>", "owner": "alice",
            "status": "retained_verified", "size": 1024, "sha256": "c" * 64,
            "job_count": 3, "message": "Exact existing bytes verified."}]
        self.plan["record_conflicts"][0]["differences"][0]["incoming"] = "<script>unsafe</script>"
        self.operation_patch()
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(response, "Already on server — verified")
        self.assertContains(response, "Exact existing bytes verified")
        self.assertContains(response, "c" * 64)
        self.assertContains(response, "&lt;script&gt;unsafe.zip&lt;/script&gt;")
        self.assertNotContains(response, "<script>unsafe")

    def test_completed_import_reports_counts_without_implicit_workspace_links(self):
        self.ready()
        job_id = "f85fa458-930a-452a-8bca-b283b43f3fb5"
        warning = "The historical input ZIP is unavailable for one imported job."
        self.operation_patch(status="completed", profile="application", result={
            "created_counts": {"jobs": 1}, "destination_jobs": [job_id, "not-a-job", "https://unsafe.test/"],
            "warnings": [warning],
        })
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(response, "Verified records")
        self.assertContains(response, "QC jobs")
        self.assertContains(response, "Existing records remain unchanged")
        self.assertContains(response, warning)
        self.assertNotContains(response, reverse("show_result", args=[job_id]))
        self.assertNotContains(response, 'href="/deliveries/')
        self.assertNotContains(response, 'href="/products/')
        self.assertNotContains(response, 'href="/data/job/')
        self.assertContains(response, "qc-admin-workspace-link")
        self.assertContains(response, "Back to workspace")
        self.assertContains(response, f'href="{reverse("dashboard_home")}"', count=1)
        self.assertNotContains(response, "Imported QC jobs")
        self.assertNotContains(response, "download its original ZIP")
        self.assertNotContains(response, job_id)
        self.assertNotContains(response, "not-a-job")
        self.assertNotContains(response, "https://unsafe.test/")

    def test_resolution_controls_remain_administrator_only_and_csrf_protected(self):
        self.additive_fixture()
        replan = self.patch("plan_import")
        payload = {"action": "resolve_conflicts", "operation_id": self.operation_id,
                   "conflict_page": 1, "resolution_plan_hash": "a" * 64, "resolution_0": "skip"}
        protected_client = Client(enforce_csrf_checks=True)
        protected_client.force_login(self.administrator)
        self.assertEqual(protected_client.post(self.url, payload).status_code, 403)
        self.user.groups.add(Group.objects.get(name=Role.PRODUCT_MANAGER.value))
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(self.url, payload).status_code, 403)
        replan.assert_not_called()

    def test_large_json_and_text_conflicts_render_bounded_checksum_evidence(self):
        self.additive_fixture()
        original_document = {"checks": "original-document-content" * 10000}
        large_text = "<script>unsafe text</script>" + "L" * 10000
        self.plan["record_conflicts"][0]["differences"] = [
            {"field": "Specification", "current": original_document, "incoming": {"checks": []}},
            {"field": "Description", "current": "Original description", "incoming": large_text},
        ]
        self.operation_patch()
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(response, "JSON object")
        self.assertContains(response, "SHA-256")
        self.assertContains(response, "&lt;script&gt;unsafe text&lt;/script&gt;")
        self.assertNotContains(response, "original-document-content")
        self.assertNotContains(response, "L" * 1000)
        self.assertLess(len(response.content), 100000)
