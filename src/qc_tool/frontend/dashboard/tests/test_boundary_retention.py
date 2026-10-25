"""Boundary retirement preserves active, historical and recovery-owned bytes."""

import io
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
from zipfile import ZipFile

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from qc_tool.common import CONFIG, JOB_OK
from qc_tool.database import selection
from qc_tool.database.transfers import recovery_files, store
from qc_tool.database.transfers.artifacts import collect_artifacts
from qc_tool.database.transfers.storage_pins import describe_pins
from qc_tool.frontend.dashboard.models import Delivery, Job
from qc_tool.frontend.dashboard.services import boundary_retention as retention, maintenance
from qc_tool.frontend.dashboard.services.boundaries import replace_boundary_package, resolve_boundary_generation
from qc_tool.frontend.dashboard.services.storage_admin import files
from qc_tool.frontend.dashboard.services.storage_admin.files import StorageError


def package(marker):
    stream = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("raster/aoi.tif", marker + b" raster")
        archive.writestr("vector/aoi.gpkg", marker + b" vector")
    stream.seek(0)
    return stream


class BoundaryRetentionTests(TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory(prefix="qc-boundary-retention-")))
        self.boundaries = self.directory / "boundaries"
        self.work = self.directory / "work"
        self.work.mkdir()
        self.enterContext(override_settings(
            MAINTENANCE_MODE=False, MEDIA_ROOT=str(self.directory / "incoming"),
            QC_TOOL_MAINTENANCE_DIR=self.directory / "maintenance",
            QC_TOOL_TRANSFER_DIR=self.directory / "transfers",
            QC_TOOL_PERSISTENT_STORAGE_ROOT="", QC_TOOL_PERSISTENT_STORAGE_ID="",
        ))
        self.enterContext(patch.dict(CONFIG, {
            "boundary_dir": self.boundaries, "work_dir": self.work, "product_dirs": [],
        }))
        self.old = replace_boundary_package(package(b"old"), self.boundaries)
        self.active = replace_boundary_package(package(b"current"), self.boundaries)
        self.old_path = self.boundaries / ".boundary-generations" / self.old.generation_id
        self.admin = get_user_model().objects.create_superuser(
            username="boundary-retention-admin", password="sufficient-test-password", email="admin@example.test",
        )
        self.client.force_login(self.admin)
        with maintenance.application_activity():
            pass
        self.url = reverse("boundaries_retention")
        self.action_url = reverse("boundaries_retention_action")

    def ready(self):
        state = maintenance.read_status()
        if not state["enabled"]:
            state = maintenance.enable(self.admin, state["generation"])
        state = maintenance.advance(state["generation"])
        self.assertEqual(state["phase"], "ready")
        return state["generation"]

    def removal_data(self, generation_id=None):
        ident = generation_id or self.old.generation_id
        preview = retention.preview_removal(ident, self.admin)
        return {"action": "remove", "generation_id": ident, "review_hash": preview["review_hash"],
                "maintenance_generation": maintenance.read_status()["generation"]}

    def remove(self):
        self.ready()
        response = self.client.post(self.action_url, self.removal_data())
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        return retention.list_trash()["entries"][0]

    def restore_data(self, operation):
        return {"action": "restore", "operation_id": operation["id"],
                "maintenance_generation": maintenance.read_status()["generation"]}

    def add_job(self):
        delivery = Delivery.objects.create(user=self.admin, filename="history.zip", size_bytes=1)
        return Job.objects.create(delivery=delivery, product_ident="test", product_description="Historical job", job_status=JOB_OK)

    def assert_active(self):
        generation = resolve_boundary_generation(self.boundaries)
        self.assertEqual(generation.generation_id, self.active.generation_id)
        self.assertEqual((generation.raster_dir / "aoi.tif").read_bytes(), b"current raster")

    def test_catalog_links_exact_active_content_and_retention_pages_are_read_only(self):
        before = {str(p): (p.lstat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
                  for p in self.directory.rglob("*") if not p.is_symlink()}
        with CaptureQueriesContext(connection) as captured:
            catalog = self.client.get(reverse("boundaries"))
            versions = self.client.get(self.url)
        self.assertContains(catalog, reverse("boundaries_upload"))
        self.assertContains(catalog, self.url)
        query = parse_qs(urlsplit(catalog.context["active_boundary"]["download_url"]).query)
        self.assertEqual(query["paths"], [".boundary-generations/" + self.active.generation_id])
        self.assertContains(versions, "Review removal")
        self.assertContains(versions, "Active package is protected")
        writes = [row["sql"] for row in captured if row["sql"].lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER "))]
        self.assertEqual(writes, [])
        after = {str(p): (p.lstat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
                 for p in self.directory.rglob("*") if not p.is_symlink()}
        self.assertEqual(before, after)

    def test_unused_version_moves_to_trash_and_exact_restore_preserves_active_selection(self):
        original_inode = self.old_path.stat().st_ino
        operation = self.remove()
        self.assertFalse(self.old_path.exists())
        self.assertEqual(operation["state"], "quarantined")
        payload = self.boundaries / retention.TRASH_DIRECTORY / operation["id"] / "payload"
        self.assertEqual((payload / "vector/aoi.gpkg").read_bytes(), b"old vector")
        self.assert_active()
        # Restoring original content is safe even after new historical rows
        # appear. It does not change the selected generation or replace bytes.
        self.add_job()
        self.assertRedirects(self.client.post(self.action_url, self.restore_data(operation)), self.url, fetch_redirect_response=False)
        self.assertEqual(self.old_path.stat().st_ino, original_inode)
        self.assertEqual((self.old_path / "raster/aoi.tif").read_bytes(), b"old raster")
        self.assertEqual(retention.list_trash()["entries"][0]["state"], "restored")
        self.assert_active()

    def test_active_version_and_any_job_history_protect_all_retained_packages(self):
        self.ready()
        with self.assertRaisesMessage(StorageError, "active boundary package"):
            retention.preview_removal(self.active.generation_id, self.admin)
        data = self.removal_data()
        self.add_job()
        response = self.client.post(self.action_url, data)
        self.assertContains(response, "Historical jobs do not record", status_code=409)
        self.assertTrue(self.old_path.exists())
        self.assertEqual(retention.list_trash()["entries"], [])

    def test_retained_restore_pins_are_checked_for_boundary_directories(self):
        operation_id = str(uuid4())
        path = store.operation_dir(operation_id, create=True) / "storage-pin.json"
        key = ".boundary-generations/" + self.old.generation_id + "/raster/aoi.tif"
        store.write_json(path, {"version": 1, "operation_id": operation_id, "destination_database": "retained_fixture",
                               "roots": {"boundaries": str(self.boundaries)},
                               "files": [{"root": "boundaries", "key": key, "size": 10, "sha256": "a" * 64}]})
        pins = describe_pins("boundaries", ".boundary-generations/" + self.old.generation_id, is_directory=True)
        self.assertEqual(len(pins), 1)
        # Independently test the exact pin guard even when the broad unknown-
        # restore-history guard already protects every boundary generation.
        with patch.object(retention, "removal_protection_reason", return_value=""):
            with self.assertRaisesMessage(StorageError, "retained restore database"):
                retention.preview_removal(self.old.generation_id, self.admin)
        path.write_text("corrupt private pin")
        with self.assertRaisesMessage(StorageError, "history could not be checked"):
            retention.preview_removal(self.old.generation_id, self.admin)
        self.assertTrue(self.old_path.exists())

    def test_removal_requires_ready_current_maintenance_and_fresh_review(self):
        data = self.removal_data()
        self.assertContains(self.client.post(self.action_url, data), "wait for readiness", status_code=409)
        generation = self.ready()
        for update in ({"maintenance_generation": generation - 1}, {"review_hash": "f" * 64}):
            response = self.client.post(self.action_url, {**self.removal_data(), **update})
            self.assertEqual(response.status_code, 409)
            self.assertTrue(self.old_path.exists())
        data = self.removal_data()
        self.active = replace_boundary_package(package(b"current"), self.boundaries)
        self.assertContains(self.client.post(self.action_url, data), "Review its removal again", status_code=409)
        self.assertTrue(self.old_path.exists())

    def test_changed_package_corrupt_selection_and_aliases_fail_closed(self):
        data = self.removal_data()
        self.ready()
        data["maintenance_generation"] = maintenance.read_status()["generation"]
        old_file = self.old_path / "raster/aoi.tif"
        original_status = old_file.stat()
        old_file.chmod(0o640)
        old_file.write_bytes(b"new raster")
        old_file.chmod(0o440)
        os.utime(old_file, ns=(original_status.st_atime_ns, original_status.st_mtime_ns))
        self.assertContains(self.client.post(self.action_url, data), "Review its removal again", status_code=409)
        pointer = self.boundaries / ".boundary-current"
        target = pointer.readlink()
        pointer.unlink()
        pointer.symlink_to("../../outside")
        with self.assertRaisesMessage(StorageError, "active boundary version could not be verified"):
            retention.preview_removal(self.old.generation_id, self.admin)
        pointer.unlink()
        pointer.symlink_to(target)
        alias = self.boundaries / "raster"
        alias.unlink()
        alias.symlink_to(".boundary-generations/" + self.old.generation_id + "/raster")
        with self.assertRaisesMessage(StorageError, "compatibility links are inconsistent"):
            retention.preview_removal(self.old.generation_id, self.admin)
        self.assertTrue(self.old_path.exists())

    def test_symlink_generation_or_shared_file_cannot_enter_trash(self):
        moved = self.directory / "retained-original"
        self.old_path.rename(moved)
        self.old_path.symlink_to(moved)
        with self.assertRaises(StorageError):
            retention.preview_removal(self.old.generation_id, self.admin)
        self.old_path.unlink()
        moved.rename(self.old_path)
        vector = self.old_path / "vector"
        vector.chmod(0o750)
        (vector / "shared.gpkg").hardlink_to(self.old_path / "raster/aoi.tif")
        vector.chmod(0o550)
        with self.assertRaisesMessage(StorageError, "contains a link"):
            retention.preview_removal(self.old.generation_id, self.admin)
        self.assertTrue(self.old_path.exists())

    def test_restore_never_overwrites_an_existing_directory_or_accepts_changed_payload(self):
        operation = self.remove()
        self.old_path.mkdir()
        sentinel = self.old_path / "keep.txt"
        sentinel.write_bytes(b"existing destination")
        response = self.client.post(self.action_url, self.restore_data(operation))
        self.assertContains(response, "already exists", status_code=409)
        self.assertEqual(sentinel.read_bytes(), b"existing destination")
        sentinel.unlink()
        self.old_path.rmdir()
        payload = self.boundaries / retention.TRASH_DIRECTORY / operation["id"] / "payload/raster/aoi.tif"
        payload.chmod(0o640)
        payload.write_bytes(b"changed retained file")
        payload.chmod(0o440)
        self.assertContains(self.client.post(self.action_url, self.restore_data(operation)), "package changed", status_code=409)
        self.assertFalse(self.old_path.exists())
        self.assertTrue(payload.exists())
        self.assert_active()

    def test_durable_intents_recover_after_lost_remove_and_restore_acknowledgements(self):
        self.ready()
        real_write = retention.write_journal
        def fail_after_move(directory, journal):
            if journal["state"] == "quarantined":
                raise OSError("lost acknowledgement")
            return real_write(directory, journal)
        with patch.object(retention, "write_journal", side_effect=fail_after_move):
            with self.assertRaises(StorageError):
                retention.remove_generation(self.old.generation_id, self.admin,
                                            maintenance.read_status()["generation"], self.removal_data()["review_hash"])
        operation = retention.list_trash()["entries"][0]
        self.assertEqual(operation["state"], "moving")
        self.assertFalse(self.old_path.exists())
        def fail_after_restore(directory, journal):
            if journal["state"] == "restored":
                raise OSError("lost acknowledgement")
            return real_write(directory, journal)
        with patch.object(retention, "write_journal", side_effect=fail_after_restore):
            response = self.client.post(self.action_url, self.restore_data(operation))
        self.assertIn(response.status_code, {409, 503})
        self.assertTrue(self.old_path.exists())
        self.assertEqual(retention.list_trash()["entries"][0]["state"], "restoring")
        self.assertRedirects(self.client.post(self.action_url, self.restore_data(operation)), self.url, fetch_redirect_response=False)
        self.assert_active()

    def test_routes_require_admin_authority_csrf_and_post_even_during_maintenance(self):
        self.ready()
        self.assertEqual(self.client.get(self.action_url).status_code, 405)
        anonymous = Client()
        self.assertIn(reverse("admin_login"), anonymous.get(self.url)["Location"])
        ordinary = get_user_model().objects.create_user(username="ordinary-boundary-user")
        anonymous.force_login(ordinary)
        self.assertEqual(anonymous.get(self.url).status_code, 403)
        self.assertEqual(anonymous.post(self.action_url, self.removal_data()).status_code, 403)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.admin)
        self.assertEqual(csrf.post(self.action_url, self.removal_data()).status_code, 403)
        csrf.get(self.url)
        response = csrf.post(self.action_url, self.removal_data(), HTTP_X_CSRFTOKEN=csrf.cookies["csrftoken"].value)
        self.assertRedirects(response, self.url, fetch_redirect_response=False)

    def test_stale_administrator_and_database_usage_failures_cannot_change_files(self):
        self.ready()
        preview = self.removal_data()
        self.admin.is_staff = False
        self.admin.save(update_fields=["is_staff"])
        with self.assertRaisesMessage(StorageError, "active administrator"):
            retention.remove_generation(self.old.generation_id, self.admin,
                                        maintenance.read_status()["generation"], preview["review_hash"])
        self.assertTrue(self.old_path.exists())

    def test_database_selection_and_unknown_or_native_restore_history_protect_all_versions(self):
        self.ready()
        data = self.removal_data()
        state = {**selection.read_state(), "revision": 1}
        with patch.object(selection, "read_state", return_value=state):
            response = self.client.post(self.action_url, data)
        self.assertContains(response, "database selection history", status_code=409)
        operation_id = str(uuid4())
        directory = store.operation_dir(operation_id, create=True)
        # A valid native import journal protects history even without an
        # activated destination or an optional file-restore plan.
        operation = {"version": 1, "id": operation_id, "kind": "import", "profile": "database", "status": "completed",
                     "actor_id": self.admin.pk, "actor_name": self.admin.username, "message": "", "error": "",
                     "result": {}, "plan": None, "created_at": store.now(), "updated_at": store.now()}
        store.write_json(directory / "operation.json", operation)
        self.assertIn("retained restore database", retention.removal_protection_reason())
        for profile in (None, "unknown_future_profile", {}, []):
            store.write_json(directory / "operation.json", {**operation, "profile": profile})
            with self.assertRaisesMessage(StorageError, "history could not be checked safely"):
                retention.removal_protection_reason()
        (directory / "operation.json").write_text("unreadable history")
        with self.assertRaisesMessage(StorageError, "history could not be checked safely"):
            retention.preview_removal(self.old.generation_id, self.admin)
        self.assertTrue(self.old_path.exists())

    def test_boundary_trash_is_private_through_browser_aliases_and_excluded_from_artifact_inventory(self):
        operation = self.remove()
        trash = self.boundaries / retention.TRASH_DIRECTORY
        visible = files.list_entries("boundaries")["entries"]
        self.assertNotIn(retention.TRASH_DIRECTORY, [entry["name"] for entry in visible])
        with self.assertRaises(StorageError):
            files.list_entries("boundaries", retention.TRASH_DIRECTORY)
        with override_settings(QC_TOOL_STORAGE_ROOTS=[{"key": "trash-alias", "label": "Alias", "path": trash}]):
            with self.assertRaises(StorageError):
                files.list_entries("extra-trash-alias")
        roots = {"boundaries": self.boundaries, "work": self.work, "incoming": self.directory / "incoming", "submissions": self.directory / "published"}
        roots["incoming"].mkdir(exist_ok=True)
        roots["submissions"].mkdir(exist_ok=True)
        inventory = collect_artifacts({"profile": "application", "accounts": [], "records": {}}, roots=roots, include_files=True)
        self.assertFalse(any(retention.TRASH_DIRECTORY in source.key for source in inventory.sources))
        self.assertFalse(any(self.old.generation_id in source.key for source in inventory.sources))
        self.assertTrue(any(self.active.generation_id in source.key for source in inventory.sources))
        native_inventory = recovery_files.collect(roots=roots, components=["boundaries"])
        self.assertFalse(any(retention.TRASH_DIRECTORY in source.key for source in native_inventory.sources))
        self.assertFalse(any(self.old.generation_id in source.key for source in native_inventory.sources))
        self.assertTrue(any(self.active.generation_id in source.key for source in native_inventory.sources))
        self.assertTrue((trash / operation["id"] / "payload").is_dir())
