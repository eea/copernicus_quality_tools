"""Database administration routes preserve reviewed requests and authority."""

import inspect
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import get_script_prefix, resolve, reverse, set_script_prefix

from qc_tool.database.transfers import service
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.dashboard.access.maintenance import is_maintenance_control_request
from qc_tool.frontend.dashboard.services import maintenance
from qc_tool.frontend.dashboard.views.admin_data_transfer import (
    data_transfer, data_transfer_download, data_transfer_status,
)


OPERATION_ID = "812d54c5-f69b-4f51-9e25-d4cbbd9a35da"
ENTRY_ROUTES = ("admin_data_transfer", "admin_data_transfer_no_slash", "admin_data_transfer_legacy")
CHILD_ROUTES = (
    "admin_data_transfer_status", "admin_data_transfer_download",
    "admin_data_transfer_status_legacy", "admin_data_transfer_download_legacy",
)


class AdminDatabaseRouteOwnershipTests(SimpleTestCase):
    def test_reverse_names_generate_the_canonical_database_paths(self):
        self.assertEqual(reverse("admin_data_transfer"), "/admin/database/")
        self.assertEqual(reverse("admin_data_transfer_status", args=[OPERATION_ID]), f"/admin/database/{OPERATION_ID}/status/")
        self.assertEqual(reverse("admin_data_transfer_download", args=[OPERATION_ID]), f"/admin/database/{OPERATION_ID}/download/")

    def test_aliases_keep_the_same_handlers_and_maintenance_control_ownership(self):
        factory = RequestFactory()
        for route in (*ENTRY_ROUTES, *CHILD_ROUTES):
            with self.subTest(route=route):
                path = reverse(route, args=[OPERATION_ID] if route in CHILD_ROUTES else [])
                target = data_transfer_status if "status" in route else data_transfer_download if "download" in route else data_transfer
                match = resolve(path)
                self.assertIs(inspect.unwrap(match.func), inspect.unwrap(target))
                self.assertEqual(str(match.func.login_url), reverse("admin_login"))
                for method in ("get", "post"):
                    request = getattr(factory, method)(path, SCRIPT_NAME="/qc-tool")
                    self.assertTrue(is_maintenance_control_request(request))

    def test_canonical_and_legacy_routes_remain_controls_under_a_script_prefix(self):
        previous = get_script_prefix()
        self.addCleanup(set_script_prefix, previous)
        set_script_prefix("/qc-tool/")
        self.assertEqual(reverse("admin_data_transfer"), "/qc-tool/admin/database/")
        for path in ("/admin/database/", "/admin/database", "/admin/data-transfer/"):
            request = RequestFactory().post(path, SCRIPT_NAME="/qc-tool")
            self.assertTrue(is_maintenance_control_request(request))


@override_settings(MAINTENANCE_MODE=False)
class AdminDatabaseRouteAccessTests(TestCase):
    def setUp(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(override_settings(
            QC_TOOL_MAINTENANCE_DIR=directory / "maintenance",
            QC_TOOL_TRANSFER_DIR=directory / "transfers",
        ))
        self.administrator = get_user_model().objects.create_user(username="database-route-administrator")
        self.administrator.groups.add(Group.objects.get(name=Role.ADMIN.value))
        self.manager = get_user_model().objects.create_user(username="database-route-manager")
        self.manager.groups.add(Group.objects.get(name=Role.PRODUCT_MANAGER.value))
        self.client.force_login(self.administrator)
        self.enterContext(patch.object(service, "schema_readiness", return_value={"ready": True, "message": ""}))
        self.enterContext(patch.object(service, "database_availability", return_value={
            "ready": False, "message": "Native backup requires PostgreSQL.", "can_create_restore_database": False,
        }))
        self.enterContext(patch.object(service, "database_control_status", return_value={}))
        self.enterContext(patch.object(service, "list_operations", return_value=[]))

    def paths(self):
        return [reverse(route) for route in ENTRY_ROUTES] + [reverse(route, args=[OPERATION_ID]) for route in CHILD_ROUTES]

    def test_anonymous_routes_use_admin_authentication_with_the_original_destination(self):
        client = Client()
        for path in self.paths():
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 302)
                destination = urlsplit(response.url)
                self.assertEqual(destination.path, reverse("admin_login"))
                self.assertEqual(parse_qs(destination.query).get("next"), [path])

    def test_product_manager_cannot_use_canonical_or_legacy_controls(self):
        self.client.force_login(self.manager)
        for path in self.paths():
            for method in ("get", "post"):
                with self.subTest(path=path, method=method):
                    self.assertEqual(getattr(self.client, method)(path).status_code, 403)

    def test_entry_aliases_keep_csrf_protection(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.administrator)
        with patch.object(service, "export_preview") as preview:
            for route in ENTRY_ROUTES:
                with self.subTest(route=route):
                    response = client.post(reverse(route), {"action": "preview_export", "scope": "all_accounts"})
                    self.assertEqual(response.status_code, 403)
            preview.assert_not_called()

    def test_entry_aliases_preserve_query_parameters_without_redirecting(self):
        for route in ENTRY_ROUTES:
            with self.subTest(route=route):
                response = self.client.get(reverse(route), {"tab": "history", "marker": "review & keep", "users": ["1", "2"]})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.wsgi_request.GET["marker"], "review & keep")
                self.assertEqual(response.wsgi_request.GET.getlist("users"), ["1", "2"])
                self.assertContains(response, f'href="{reverse("admin_data_transfer")}"')

    def test_entry_aliases_keep_review_post_bodies_during_maintenance(self):
        maintenance.enable(self.administrator, expected_generation=0)
        payload = {"section": "users", "action": "preview_export", "scope": "all_accounts", "marker": "review & keep"}
        for route in ENTRY_ROUTES:
            with self.subTest(route=route), patch.object(
                service, "export_preview", side_effect=service.TransferError("Reviewed request reached the export service."),
            ) as preview:
                response = self.client.post(reverse(route), payload)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.wsgi_request.POST["marker"], payload["marker"])
                preview.assert_called_once_with({"profile": "accounts", "user_ids": [], "include_files": False}, actor=self.administrator)

    def test_legacy_entry_generates_canonical_progress_and_download_links(self):
        operation = {"id": OPERATION_ID, "kind": "export", "profile": "accounts", "status": "running",
                     "downloadable": False, "runner_active": True, "recoverable": False, "cancellable": False}
        with patch.object(service, "get_operation", return_value=operation):
            response = self.client.get(reverse("admin_data_transfer_legacy"), {"operation": OPERATION_ID})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'data-transfer-status-url="{reverse("admin_data_transfer_status", args=[OPERATION_ID])}"')
        self.assertContains(response, f'href="{reverse("admin_data_transfer")}?operation={OPERATION_ID}#transfer-operation"')
        operation.update(status="completed", downloadable=True, runner_active=False)
        with patch.object(service, "get_operation", return_value=operation):
            response = self.client.get(reverse("admin_data_transfer_legacy"), {"operation": OPERATION_ID})
        self.assertContains(response, f'href="{reverse("admin_data_transfer_download", args=[OPERATION_ID])}"')

    def test_status_and_download_aliases_remain_authorized_reads_in_maintenance(self):
        maintenance.enable(self.administrator, expected_generation=0)
        operation = {"id": OPERATION_ID, "kind": "export", "status": "completed", "downloadable": True,
                     "runner_active": False, "recoverable": False, "cancellable": False}
        with (
            patch.object(service, "get_operation", return_value=operation) as status,
            patch.object(service, "download_operation", side_effect=lambda *args, **kwargs: (io.BytesIO(b"verified-zip"), {"filename": "backup.zip"})) as download,
        ):
            for route in CHILD_ROUTES:
                with self.subTest(route=route):
                    response = self.client.get(reverse(route, args=[OPERATION_ID]))
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response["X-QC-Maintenance"], "on")
                    if "download" in route:
                        self.assertEqual(b"".join(response.streaming_content), b"verified-zip")
                    else:
                        self.assertEqual(response.json()["id"], OPERATION_ID)
            self.assertEqual(status.call_count, 2)
            self.assertEqual(download.call_count, 2)
