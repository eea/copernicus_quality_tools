"""The Admin storage workflow keeps files recoverable and record-bound."""

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import DatabaseError, connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from qc_tool.common import CONFIG, JOB_OK
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.dashboard.models import Delivery, Job
from qc_tool.frontend.dashboard.services import maintenance
from qc_tool.frontend.dashboard.services.maintenance.operations import pin_operation
from qc_tool.frontend.dashboard.services.maintenance.state import file_lock
from qc_tool.frontend.dashboard.services.storage_admin import files, trash
from qc_tool.frontend.dashboard.views import admin_storage as views


class AdminStorageTests(TestCase):
    def setUp(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.incoming = directory / "incoming"
        self.work = directory / "work"
        self.published = directory / "published"
        self.boundaries = directory / "boundaries"
        self.definitions = directory / "definitions"
        for root in (self.incoming, self.work, self.published, self.boundaries, self.definitions):
            root.mkdir()
        self.enterContext(override_settings(
            MAINTENANCE_MODE=False, MEDIA_ROOT=str(self.incoming),
            QC_TOOL_MAINTENANCE_DIR=directory / "maintenance",
            QC_TOOL_TRANSFER_DIR=directory / "transfers",
            S3_CREDENTIALS_DIR=directory / "credentials",
        ))
        self.enterContext(patch.dict(CONFIG, {
            "work_dir": self.work, "incoming_dir": self.incoming,
            "submission_dir": self.published, "boundary_dir": self.boundaries,
            "product_dirs": [self.definitions],
        }))
        self.administrator = get_user_model().objects.create_superuser(
            username="storage-administrator", email="storage@example.test",
            password="sufficient-test-password",
        )
        self.client.force_login(self.administrator)
        self.payload = b"preinstalled delivery ZIP bytes"
        self.relative_path = "preinstalled-owner/original.zip"
        self.original = self.write_file("incoming", self.relative_path, self.payload)
        maintenance.read_status()

    def write_file(self, area, path, payload):
        root = {"incoming": self.incoming, "jobs": self.work, "published": self.published}[area]
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        return destination

    def ready(self):
        state = maintenance.read_status()
        if not state["enabled"]:
            state = maintenance.enable(self.administrator, state["generation"])
        state = maintenance.advance(state["generation"])
        self.assertEqual(state["phase"], "ready")
        return state["generation"]

    def detail(self, *, area="incoming", path=None, verify=False, client=None):
        query = {"area": area, "path": path or self.relative_path}
        if verify:
            query["verify"] = "1"
        return (client or self.client).get(reverse("admin_storage_file"), query)

    def quarantine_data(self, *, area="incoming", path=None, generation=None):
        path = path or self.relative_path
        review = self.detail(area=area, path=path).context["review"]
        return {"action": "quarantine", "area": area, "path": path,
                "generation": maintenance.read_status()["generation"] if generation is None else generation,
                "filename_confirmation": path.rsplit("/", 1)[-1], "confirmed": "on",
                "review_hash": review["review_hash"]}

    def quarantine(self):
        response = self.client.post(reverse("admin_storage_action"), self.quarantine_data())
        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.original.exists())
        listing = self.client.get(reverse("admin_storage_trash"), {"area": "incoming"})
        entry = listing.context["trash_listing"]["entries"][0]
        return entry

    def restore_data(self, operation):
        return {"action": "restore", "area": "incoming", "operation_id": operation["id"],
                "generation": maintenance.read_status()["generation"]}

    def linked_records(self, *, checksum=True):
        owner = get_user_model().objects.create_user(username="preinstalled-owner")
        digest = sha256(self.payload).hexdigest()
        delivery = Delivery.objects.create(
            user=owner, filename="original.zip", size_bytes=len(self.payload),
            content_sha256=digest if checksum else "",
        )
        job = Job.objects.create(
            delivery=delivery, product_ident="test", product_description="Imported QC history",
            job_status=JOB_OK, input_sha256=digest if checksum else "",
        )
        return delivery, job

    def assert_no_sql_writes(self, captured):
        writes = [row["sql"] for row in captured if row["sql"].lstrip().upper().startswith(
            ("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER ", "DROP "),
        )]
        self.assertEqual(writes, [])

    def test_filesystem_browsing_and_orphan_zip_inspection_need_no_delivery_or_job_rows(self):
        self.assertEqual((Delivery.objects.count(), Job.objects.count()), (0, 0))
        home = self.client.get(reverse("admin_storage"))
        self.assertContains(home, "Delivery uploads")
        self.assertContains(home, "QC job artifacts")
        self.assertContains(home, "Published submissions")
        owner = self.client.get(reverse("admin_storage"), {"area": "incoming", "path": "preinstalled-owner"})
        self.assertContains(owner, "original.zip")
        self.assertEqual(owner.context["listing"]["entries"][0]["path"], self.relative_path)
        inspected = self.detail()
        self.assertContains(inspected, "Unlinked")
        self.assertTrue(inspected.context["review"]["can_quarantine"])
        self.assertIsNone(inspected.context["evidence"])
        self.assertEqual((Delivery.objects.count(), Job.objects.count()), (0, 0))

    def test_listing_and_default_file_details_never_read_file_bytes_or_hash_history(self):
        with patch.object(files, "open_file", side_effect=AssertionError("File bytes must not be read")):
            listed = self.client.get(reverse("admin_storage"), {"area": "incoming", "path": "preinstalled-owner"})
            detailed = self.detail()
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(detailed.status_code, 200)
        self.assertIsNone(detailed.context["evidence"])

    def test_orphan_download_is_an_attachment_with_safe_headers_and_original_bytes(self):
        response = self.client.get(reverse("admin_storage_download"), {"area": "incoming", "path": self.relative_path})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/octet-stream")
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="original.zip"')
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Content-Security-Policy"], "sandbox")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("private", response["Cache-Control"])
        self.assertEqual(b"".join(response.streaming_content), self.payload)

    def test_explicit_verification_proves_the_exact_linked_job_checksum_and_size(self):
        delivery, job = self.linked_records()
        default = self.detail()
        self.assertContains(default, "Not verified")
        self.assertFalse(default.context["usage"]["job_matches"][0]["verified"])
        response = self.detail(verify=True)
        self.assertEqual(response.context["evidence"], {"sha256": sha256(self.payload).hexdigest(), "size": len(self.payload)})
        self.assertTrue(response.context["usage"]["job_matches"][0]["verified"])
        self.assertContains(response, "ZIP checksum and size match this run")
        for model, obj in ((Delivery, delivery), (Job, job)):
            self.assertContains(response, reverse("admin_database_record", args=[model._meta.db_table, str(obj.pk)]))
        delivery.size_bytes += 1
        delivery.save(update_fields=["size_bytes"])
        drifted = self.detail(verify=True)
        self.assertFalse(drifted.context["usage"]["job_matches"][0]["verified"])
        self.assertNotContains(drifted, "ZIP checksum and size match this run")

    def test_a_historical_job_without_checksum_is_not_presented_as_verified(self):
        self.linked_records(checksum=False)
        response = self.detail(verify=True)
        self.assertContains(response, "Historical unavailable")
        self.assertFalse(response.context["usage"]["job_matches"][0]["verified"])
        self.assertNotContains(response, "ZIP checksum and size match this run")

    def test_output_zip_with_identical_input_bytes_is_not_presented_as_historical_input(self):
        _delivery, job = self.linked_records()
        path = "job_" + job.pk.hex + "/output.d/result.zip"
        self.write_file("jobs", path, self.payload)
        response = self.detail(area="jobs", path=path, verify=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["evidence"], {"sha256": sha256(self.payload).hexdigest(), "size": len(self.payload)})
        self.assertEqual(response.context["usage"]["status"], "linked")
        self.assertEqual(response.context["usage"]["job_matches"], [])
        self.assertEqual(response.context["usage"]["verified_jobs"], [])
        self.assertNotContains(response, "ZIP checksum and size match this run")
        self.assertFalse(response.context["review"]["can_quarantine"])
        downloaded = self.client.get(reverse("admin_storage_download"), {"area": "jobs", "path": path})
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(b"".join(downloaded.streaming_content), self.payload)

    def test_file_changed_during_checksum_verification_requires_a_new_review(self):
        original = self.original

        class MutatingHash:
            def __init__(self):
                self.hash = sha256()
                self.changed = False

            def update(self, block):
                self.hash.update(block)
                if not self.changed:
                    self.changed = True
                    with original.open("ab") as handle:
                        handle.write(b"changed while reading")

            def hexdigest(self):
                return self.hash.hexdigest()

        with patch.object(views, "hashlib", SimpleNamespace(sha256=MutatingHash)):
            response = self.detail(verify=True)
        self.assertContains(response, "The file changed while it was checked", status_code=409)
        self.assertNotContains(response, "ZIP checksum and size match this run", status_code=409)

    def test_verification_cannot_attribute_a_swapped_parent_directory_descriptor_to_the_reviewed_zip(self):
        self.linked_records()
        self.original.write_bytes(b"X" * len(self.payload))
        alternate = self.incoming / "alternate-owner"
        alternate.mkdir()
        (alternate / self.original.name).write_bytes(self.payload)
        parent, parked = self.original.parent, self.incoming / "parked-owner"
        real_open = files.open_file

        def swapped_open(area, path):
            parent.rename(parked)
            alternate.rename(parent)
            try:
                handle = real_open(area, path)
            finally:
                parent.rename(alternate)
                parked.rename(parent)
            return handle

        with patch.object(files, "open_file", side_effect=swapped_open):
            response = self.detail(verify=True)
        self.assertContains(response, "The file changed while it was opened", status_code=409)
        self.assertNotContains(response, "ZIP checksum and size match this run", status_code=409)
        self.assertEqual(self.original.read_bytes(), b"X" * len(self.payload))

    def test_all_storage_routes_keep_anonymous_visitors_in_admin_login(self):
        self.client.logout()
        for name in ("admin_storage", "admin_storage_file", "admin_storage_download", "admin_storage_trash", "admin_storage_action"):
            with self.subTest(route=name):
                response = self.client.get(reverse(name), {"area": "incoming", "path": self.relative_path})
                self.assertEqual(response.status_code, 302)
                target = urlsplit(response["Location"])
                self.assertEqual(target.path, reverse("admin_login"))
                self.assertEqual(urlsplit(parse_qs(target.query)["next"][0]).path, reverse(name))

    def test_product_managers_and_ordinary_staff_cannot_use_storage_routes(self):
        manager = get_user_model().objects.create_user(username="storage-manager")
        manager.groups.add(Group.objects.get(name=Role.PRODUCT_MANAGER.value))
        staff = get_user_model().objects.create_user(username="storage-staff")
        get_user_model().objects.filter(pk=staff.pk).update(is_staff=True)
        staff.refresh_from_db()
        for user in (manager, staff):
            self.client.force_login(user)
            for name in ("admin_storage", "admin_storage_file", "admin_storage_download", "admin_storage_trash", "admin_storage_action"):
                with self.subTest(user=user.username, route=name):
                    response = self.client.get(reverse(name), {"area": "incoming", "path": self.relative_path})
                    self.assertEqual(response.status_code, 403)
            self.assertEqual(self.client.post(reverse("admin_storage_action"), {"action": "quarantine"}).status_code, 403)
        self.assertTrue(self.original.exists())

    def test_storage_action_requires_csrf_even_while_maintenance_is_ready(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.administrator)
        self.ready()
        payload = self.quarantine_data()
        self.assertEqual(client.post(reverse("admin_storage_action"), payload).status_code, 403)
        self.assertTrue(self.original.exists())
        self.detail(client=client)
        token = client.cookies["csrftoken"].value
        response = client.post(reverse("admin_storage_action"), payload, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.original.exists())

    def test_storage_http_methods_preserve_the_maintenance_write_fence(self):
        self.assertEqual(self.client.get(reverse("admin_storage_action")).status_code, 405)
        for name in ("admin_storage", "admin_storage_file", "admin_storage_download", "admin_storage_trash"):
            with self.subTest(route=name, phase="off"):
                self.assertEqual(self.client.post(reverse(name)).status_code, 405)
        self.ready()
        self.assertEqual(self.client.get(reverse("admin_storage_action")).status_code, 405)
        for name in ("admin_storage", "admin_storage_file", "admin_storage_download", "admin_storage_trash"):
            with self.subTest(route=name, phase="ready"):
                self.assertEqual(self.client.post(reverse(name)).status_code, 503)

    def test_quarantine_waits_for_ready_maintenance(self):
        payload = self.quarantine_data()
        response = self.client.post(reverse("admin_storage_action"), payload)
        self.assertContains(response, "wait for readiness", status_code=409)
        state = maintenance.enable(self.administrator, maintenance.read_status()["generation"])
        payload["generation"] = state["generation"]
        response = self.client.post(reverse("admin_storage_action"), payload)
        self.assertContains(response, "wait for readiness", status_code=409)
        self.assertTrue(self.original.exists())

    def test_quarantine_rejects_stale_generation_missing_confirmation_and_changed_review(self):
        generation = self.ready()
        base = self.quarantine_data()
        for changes, message in (
            ({"generation": ""}, "Maintenance changed"),
            ({"generation": generation + 1}, "Maintenance changed"),
            ({"filename_confirmation": "another.zip"}, "Confirm the filename"),
            ({"confirmed": ""}, "Confirm the filename"),
            ({"review_hash": "f" * 64}, "Review it again"),
        ):
            with self.subTest(changes=changes):
                response = self.client.post(reverse("admin_storage_action"), {**base, **changes})
                self.assertContains(response, message, status_code=409)
                self.assertEqual(self.original.read_bytes(), self.payload)

    def test_file_details_display_the_same_snapshot_as_the_review_and_reject_later_changes(self):
        generation = self.ready()
        real_preview = trash.preview_quarantine
        reviewed_payload = b"replacement bytes reviewed before display"

        def replace_before_preview(*args, **kwargs):
            self.original.write_bytes(reviewed_payload)
            return real_preview(*args, **kwargs)

        with patch.object(trash, "preview_quarantine", side_effect=replace_before_preview):
            response = self.detail()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["entry"], response.context["review"]["entry"])
        self.assertEqual(response.context["entry"]["size_bytes"], len(reviewed_payload))
        self.original.write_bytes(b"different bytes installed after the review")
        action = self.client.post(reverse("admin_storage_action"), {
            "action": "quarantine", "area": "incoming", "path": self.relative_path,
            "generation": generation, "review_hash": response.context["review"]["review_hash"],
            "filename_confirmation": self.original.name, "confirmed": "on",
        })
        self.assertContains(action, "Review it again", status_code=409)
        self.assertEqual(self.original.read_bytes(), b"different bytes installed after the review")

    def test_a_database_transfer_pin_prevents_storage_moves_even_when_maintenance_is_ready(self):
        generation = self.ready()
        payload = self.quarantine_data()
        with file_lock("control"):
            pin_operation(uuid4(), "import", generation)
        detail = self.detail()
        self.assertTrue(detail.context["storage_overview"]["transfer_url"])
        self.assertNotContains(detail, 'name="filename_confirmation"')
        response = self.client.post(reverse("admin_storage_action"), payload)
        self.assertContains(response, "owns maintenance", status_code=409)
        self.assertEqual(self.original.read_bytes(), self.payload)

    def test_linked_zip_and_specification_or_published_files_remain_protected(self):
        self.linked_records()
        self.ready()
        specification = "job_" + uuid4().hex + "/original-definition.json"
        self.write_file("jobs", specification, b'{"description":"original specification bytes"}')
        published = "published/unlinked/output.d/report.pdf"
        self.write_file("published", published, b"retained publication")
        for area, path in (("incoming", self.relative_path), ("jobs", specification), ("published", published)):
            with self.subTest(area=area):
                preview = self.detail(area=area, path=path)
                self.assertFalse(preview.context["review"]["can_quarantine"])
                response = self.client.post(reverse("admin_storage_action"), self.quarantine_data(area=area, path=path))
                self.assertEqual(response.status_code, 409)
                self.assertTrue({"incoming": self.incoming, "jobs": self.work, "published": self.published}[area].joinpath(path).exists())

    def test_database_usage_failure_disables_changes_without_exposing_database_details(self):
        self.ready()
        payload = self.quarantine_data()
        with patch.object(Delivery.objects, "filter", side_effect=DatabaseError("private database password")):
            preview = self.detail()
            response = self.client.post(reverse("admin_storage_action"), payload)
        self.assertFalse(preview.context["review"]["can_quarantine"])
        self.assertContains(response, "could not be checked safely", status_code=409)
        self.assertNotContains(response, "private database password", status_code=409)
        self.assertTrue(self.original.exists())

    def test_quarantine_and_restore_keep_original_bytes_and_never_overwrite(self):
        self.ready()
        operation = self.quarantine()
        self.assertEqual(operation["state"], "quarantined")
        response = self.client.post(reverse("admin_storage_action"), self.restore_data(operation))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.original.read_bytes(), self.payload)
        operation = self.quarantine()
        self.original.write_bytes(b"newly installed different bytes")
        response = self.client.post(reverse("admin_storage_action"), self.restore_data(operation))
        self.assertContains(response, "already exists", status_code=409)
        self.assertEqual(self.original.read_bytes(), b"newly installed different bytes")
        private = self.incoming / files.TRASH_DIRECTORY / operation["id"] / "payload"
        self.assertEqual(private.read_bytes(), self.payload)

    def test_matching_imported_records_allow_verified_restore_of_a_previously_unlinked_zip(self):
        self.ready()
        operation = self.quarantine()
        delivery, job = self.linked_records()
        response = self.client.post(reverse("admin_storage_action"), self.restore_data(operation))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.original.read_bytes(), self.payload)
        checked = self.detail(verify=True)
        self.assertEqual(checked.context["usage"]["verified_jobs"][0]["id"], str(job.pk))
        self.assertEqual(checked.context["usage"]["links"][0]["id"], str(delivery.pk))

    def test_different_imported_checksum_keeps_the_zip_in_recoverable_trash(self):
        self.ready()
        operation = self.quarantine()
        delivery, _job = self.linked_records()
        delivery.content_sha256 = "b" * 64
        delivery.save(update_fields=["content_sha256"])
        response = self.client.post(reverse("admin_storage_action"), self.restore_data(operation))
        self.assertContains(response, "does not match", status_code=409)
        self.assertFalse(self.original.exists())
        private = self.incoming / files.TRASH_DIRECTORY / operation["id"] / "payload"
        self.assertEqual(private.read_bytes(), self.payload)

    @override_settings(SESSION_SAVE_EVERY_REQUEST=True)
    def test_maintenance_storage_reads_and_actions_never_write_sql_or_database_sessions(self):
        self.ready()
        with CaptureQueriesContext(connection) as captured:
            self.assertEqual(self.client.get(reverse("admin_storage")).status_code, 200)
            operation = self.quarantine()
            response = self.client.post(reverse("admin_storage_action"), self.restore_data(operation))
            self.assertEqual(response.status_code, 302)
        self.assert_no_sql_writes(captured)
        self.assertEqual(self.original.read_bytes(), self.payload)

    def test_job_record_details_link_exact_storage_locations_without_workspace_redirects(self):
        _delivery, job = self.linked_records()
        response = self.client.get(reverse("admin_database_record", args=[Job._meta.db_table, str(job.pk)]))
        self.assertContains(response, "Server files")
        links = response.context["record_storage_links"]
        self.assertEqual([item["area"] for item in links], ["jobs", "incoming"])
        self.assertEqual(links[0]["path"], "job_" + job.pk.hex)
        self.assertEqual(links[1]["path"], self.relative_path)
        for link in links:
            self.assertTrue(urlsplit(link["url"]).path.startswith(reverse("admin_storage")))

    def test_traversal_and_private_storage_are_unavailable_through_http(self):
        for path in ("../original.zip", "preinstalled-owner/../original.zip", ".qc-tool-trash/operation/payload"):
            with self.subTest(path=path):
                response = self.detail(path=path)
                self.assertEqual(response.status_code, 400)
        self.assertTrue(self.original.exists())
