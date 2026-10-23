"""Filesystem administration is confined, reversible and maintenance guarded."""

from pathlib import Path
from hashlib import sha256
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4
import os

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from qc_tool.common import CONFIG
from qc_tool.database.transfers import store
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.dashboard.models import Delivery, Job
from qc_tool.frontend.dashboard.services import maintenance
from qc_tool.frontend.dashboard.services.maintenance.operations import pin_operation, unpin_operation
from qc_tool.frontend.dashboard.services.maintenance.state import file_lock
from qc_tool.frontend.dashboard.services.storage_admin import files, trash


class StorageFixture:
    def setUp(self):
        super().setUp()
        self.root = Path(self.enterContext(TemporaryDirectory(prefix="qc-storage-admin-")))
        self.incoming, self.work, self.published = (self.root / name for name in ("incoming", "work", "published"))
        self.boundaries = self.root / "boundaries"
        for path in (self.incoming, self.work, self.published, self.boundaries):
            path.mkdir()
        self.enterContext(patch.dict(CONFIG, work_dir=self.work, incoming_dir=self.incoming,
            submission_dir=self.published, boundary_dir=self.boundaries, product_dirs=[]))
        self.enterContext(override_settings(MEDIA_ROOT=self.incoming,
            S3_CREDENTIALS_DIR=self.root / "credentials", QC_TOOL_MAINTENANCE_DIR=self.root / "maintenance",
            QC_TOOL_TRANSFER_DIR=self.root / "transfers", MAINTENANCE_MODE=False))
        self.owner_directory = self.incoming / "alice"
        self.owner_directory.mkdir()
        self.archive = self.owner_directory / "orphan.zip"
        self.archive.write_bytes(b"retained archive bytes")
        self.job_id = uuid4()
        self.job_directory = self.work / ("job_" + self.job_id.hex)
        self.job_directory.mkdir()


class StorageFilesTests(StorageFixture, SimpleTestCase):
    def test_areas_and_pages_read_disk_without_database_or_control_disclosure(self):
        for name in ("maintenance", "data-transfer", "s3_credentials", "product_definitions"):
            (self.work / name).mkdir()
        (self.work / "worker.token").write_text("private-worker-token")
        stdout = self.work / ("job." + str(self.job_id) + ".stdout")
        stdout.write_bytes(b"stdout")
        (self.work / ("job_" + uuid4().hex)).write_text("not a job directory")
        listing = files.list_entries("jobs")
        self.assertEqual({entry["name"] for entry in listing["entries"]}, {self.job_directory.name, stdout.name})
        self.assertTrue(all(area["available"] for area in files.storage_areas()))
        self.assertTrue(next(area for area in files.storage_areas() if area["key"] == "published")["read_only"])
        self.assertNotIn(str(self.root), str(files.storage_areas()))

    def test_listing_is_paginated_filtered_and_explicitly_scan_bounded(self):
        for number in range(6):
            (self.owner_directory / f"delivery-{number}.zip").write_bytes(b"z")
        listing = files.list_entries("incoming", "alice", page=2, page_size=2, query="delivery-")
        self.assertEqual((listing["total"], listing["page"], len(listing["entries"])), (6, 2, 2))
        self.assertTrue(listing["has_previous"] and listing["has_next"])
        with patch.object(files, "MAX_SCAN_ENTRIES", 2):
            self.assertTrue(files.list_entries("incoming", "alice")["scan_limited"])

    def test_traversal_absolute_hidden_and_unreviewed_work_paths_are_rejected(self):
        for path in ("../outside", "/etc/passwd", "alice/../orphan.zip", "alice//orphan.zip",
                     "alice\\orphan.zip", "alice/.previous", "alice/.resumable/part", "alice/a\x00b"):
            with self.subTest(path=path), self.assertRaises(files.StorageError):
                files.inspect_entry("incoming", path)
        for path in ("worker.token", "maintenance/state.json", "product_definitions/product.json", "s3_credentials/key"):
            with self.subTest(path=path), self.assertRaises(files.StorageError):
                files.open_file("jobs", path)
        with self.assertRaises(files.StorageError):
            files.list_entries("arbitrary-root")

    def test_links_and_special_files_are_never_followed_or_downloaded(self):
        outside = self.root / "outside-secret"
        outside.write_text("secret")
        (self.owner_directory / "link.zip").symlink_to(outside)
        (self.incoming / "linked-owner").symlink_to(self.owner_directory, target_is_directory=True)
        os.link(outside, self.owner_directory / "hardlink.zip")
        os.mkfifo(self.owner_directory / "pipe.zip")
        for path in ("alice/link.zip", "linked-owner/orphan.zip", "alice/hardlink.zip", "alice/pipe.zip"):
            with self.subTest(path=path), self.assertRaises(files.StorageError):
                files.open_file("incoming", path)
        self.assertEqual([entry["name"] for entry in files.list_entries("incoming", "alice")["entries"]], ["orphan.zip"])

    def test_configured_root_links_and_protected_root_overlap_are_rejected(self):
        linked = self.root / "linked-incoming"
        linked.symlink_to(self.incoming, target_is_directory=True)
        with override_settings(MEDIA_ROOT=linked), self.assertRaises(files.StorageError):
            files.list_entries("incoming")
        with override_settings(MEDIA_ROOT=self.work), self.assertRaises(files.StorageError):
            files.list_entries("incoming")
        with patch.dict(CONFIG, submission_dir=self.work), self.assertRaises(files.StorageError):
            files.list_entries("published")

    def test_scoped_work_subdirectories_are_allowed_but_job_control_overlaps_are_hidden(self):
        incoming = self.work / "incoming"
        incoming.mkdir()
        with override_settings(MEDIA_ROOT=incoming):
            self.assertEqual(files.list_entries("incoming")["entries"], [])
        with override_settings(QC_TOOL_MAINTENANCE_DIR=self.job_directory / "control"):
            self.assertEqual(files.list_entries("jobs")["entries"], [])
            with self.assertRaises(files.StorageError):
                files.list_entries("jobs", self.job_directory.name)

    def test_download_descriptor_remains_on_verified_file_after_path_swap(self):
        handle = files.open_file("incoming", "alice/orphan.zip")
        self.archive.rename(self.owner_directory / "renamed.zip")
        self.archive.symlink_to(self.root / "unavailable-secret")
        with handle:
            self.assertEqual(handle.read(), b"retained archive bytes")

    def test_job_originals_and_published_files_have_no_quarantine_capability(self):
        for name in ("input.d/original.zip", "tmp.d/temporary.tif", "product.json", "result.json", "snapshot.pdf"):
            path = self.job_directory / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"original")
            relative = self.job_directory.name + "/" + name
            self.assertTrue(files.quarantine_reason("jobs", relative, files.inspect_entry("jobs", relative)))
        for name in ("output.d/errors.geojson", "job.log", "custom_report.pdf"):
            path = self.job_directory / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"artifact")
            relative = self.job_directory.name + "/" + name
            self.assertEqual(files.quarantine_reason("jobs", relative, files.inspect_entry("jobs", relative)), "")
        self.assertTrue(files.quarantine_reason("published", "snapshot.zip", {"kind": "file"}))


class StorageTrashTests(StorageFixture, TestCase):
    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.actor = User.objects.create_user("storage-admin", password="test-password")
        self.actor.groups.add(Group.objects.get(name=Role.ADMIN.value))
        self.actor.refresh_from_db()
        self.owner = User.objects.create_user("alice")
        self.generation = maintenance.enable(self.actor, 0)["generation"]
        self.assertEqual(maintenance.advance(self.generation)["phase"], "ready")

    def preview(self):
        return trash.preview_quarantine("incoming", "alice/orphan.zip", self.actor)

    def move(self):
        return trash.quarantine("incoming", "alice/orphan.zip", self.actor,
                                self.generation, self.preview()["review_hash"])

    def payload(self, operation):
        return self.incoming / files.TRASH_DIRECTORY / operation["id"] / "payload"

    def test_preview_does_not_write_and_missing_trash_is_an_empty_listing(self):
        with CaptureQueriesContext(connection) as queries:
            preview = self.preview()
            listing = trash.list_trash("incoming")
        self.assertTrue(preview["can_quarantine"])
        self.assertEqual(listing["entries"], [])
        self.assertFalse((self.incoming / files.TRASH_DIRECTORY).exists())
        self.assertEqual([query["sql"] for query in queries if query["sql"].lstrip().upper().startswith(
            ("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER ", "DROP "))], [])

    def test_quarantine_and_restore_preserve_bytes_and_do_not_mutate_database(self):
        with CaptureQueriesContext(connection) as queries:
            operation = self.move()
            self.assertFalse(self.archive.exists())
            self.assertEqual(self.payload(operation).read_bytes(), b"retained archive bytes")
            self.assertEqual(trash.list_trash("incoming")["entries"][0]["state"], "quarantined")
            restored = trash.restore("incoming", operation["id"], self.actor, self.generation)
        self.assertEqual(restored["state"], "restored")
        self.assertEqual(self.archive.read_bytes(), b"retained archive bytes")
        self.assertEqual(self.archive.stat().st_nlink, 1)
        self.assertFalse(self.payload(operation).exists())
        self.assertEqual(trash.restore("incoming", operation["id"], self.actor, self.generation)["state"], "restored")
        self.assertEqual([query["sql"] for query in queries if query["sql"].lstrip().upper().startswith(
            ("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER ", "DROP "))], [])

    def test_restore_never_overwrites_a_new_file_at_the_original_path(self):
        operation = self.move()
        self.archive.write_bytes(b"new retained file")
        with self.assertRaisesMessage(files.StorageError, "not overwritten"):
            trash.restore("incoming", operation["id"], self.actor, self.generation)
        self.assertEqual(self.archive.read_bytes(), b"new retained file")
        self.assertEqual(self.payload(operation).read_bytes(), b"retained archive bytes")

    def test_file_created_during_restore_is_never_overwritten(self):
        operation = self.move()
        link = os.link
        def competing_file(source, destination, *args, **kwargs):
            self.archive.write_bytes(b"concurrent retained file")
            return link(source, destination, *args, **kwargs)
        with patch.object(trash.os, "link", side_effect=competing_file), self.assertRaisesMessage(files.StorageError, "not overwritten"):
            trash.restore("incoming", operation["id"], self.actor, self.generation)
        self.assertEqual(self.archive.read_bytes(), b"concurrent retained file")
        self.assertEqual(self.payload(operation).read_bytes(), b"retained archive bytes")

    def test_matching_linked_zip_can_restore_after_delivery_records_are_imported(self):
        payload = self.archive.read_bytes()
        operation = self.move()
        delivery = Delivery.objects.create(user=self.owner, filename="orphan.zip", size_bytes=len(payload),
                                           content_sha256=sha256(payload).hexdigest())
        restored = trash.restore("incoming", operation["id"], self.actor, self.generation)
        self.assertEqual(restored["state"], "restored")
        self.assertEqual(self.archive.read_bytes(), payload)
        self.assertTrue(Delivery.objects.filter(pk=delivery.pk).exists())

    def test_unknown_or_different_current_delivery_checksum_blocks_restore(self):
        payload = self.archive.read_bytes()
        operation = self.move()
        delivery = Delivery.objects.create(user=self.owner, filename="orphan.zip", size_bytes=len(payload))
        for checksum in ("", sha256(b"different bytes").hexdigest()):
            Delivery.objects.filter(pk=delivery.pk).update(content_sha256=checksum)
            with self.subTest(checksum=checksum), self.assertRaises(files.StorageError):
                trash.restore("incoming", operation["id"], self.actor, self.generation)
            self.assertFalse(self.archive.exists())
            self.assertEqual(self.payload(operation).read_bytes(), payload)

    def test_historical_job_checksum_can_verify_a_retained_zip_without_active_deliveries(self):
        payload = self.archive.read_bytes()
        operation = self.move()
        delivery = Delivery.objects.create(user=self.owner, filename="orphan.zip", size_bytes=len(payload), is_deleted=True)
        Job.objects.create(delivery=delivery, product_ident="test", product_description="Historical job",
                           input_sha256=sha256(payload).hexdigest(), job_status="ok")
        self.assertEqual(trash.restore("incoming", operation["id"], self.actor, self.generation)["state"], "restored")
        self.assertEqual(self.archive.read_bytes(), payload)

    def test_changed_review_is_rejected_before_creating_a_trash_operation(self):
        preview = self.preview()
        self.archive.write_bytes(b"changed file")
        with self.assertRaisesMessage(files.StorageError, "changed"):
            trash.quarantine("incoming", "alice/orphan.zip", self.actor, self.generation, preview["review_hash"])
        self.assertEqual(self.archive.read_bytes(), b"changed file")
        self.assertFalse((self.incoming / files.TRASH_DIRECTORY).exists())

    def test_source_parent_replacement_cannot_redirect_a_reviewed_move(self):
        preview = self.preview()
        open_file_at = files._open_file_at
        retained_directory = self.incoming / "retained-alice"
        def replace_parent(area, path, parent, name):
            self.owner_directory.rename(retained_directory)
            self.owner_directory.mkdir()
            self.archive.write_bytes(b"competing archive bytes")
            return open_file_at(area, path, parent, name)
        with patch.object(files, "_open_file_at", side_effect=replace_parent), self.assertRaisesMessage(
            files.StorageError, "folder changed"
        ):
            trash.quarantine("incoming", "alice/orphan.zip", self.actor, self.generation, preview["review_hash"])
        self.assertEqual(self.archive.read_bytes(), b"competing archive bytes")
        self.assertEqual((retained_directory / "orphan.zip").read_bytes(), b"retained archive bytes")
        self.assertFalse((self.incoming / files.TRASH_DIRECTORY).exists())

    def test_destination_parent_replacement_during_verification_keeps_payload_in_trash(self):
        from qc_tool.frontend.dashboard.services.storage_admin import references
        operation = self.move()
        assert_restore_safe = references.assert_restore_safe
        retained_directory = self.incoming / "retained-alice"
        def replace_parent(*args, **kwargs):
            result = assert_restore_safe(*args, **kwargs)
            self.owner_directory.rename(retained_directory)
            self.owner_directory.mkdir()
            return result
        with patch.object(references, "assert_restore_safe", side_effect=replace_parent), self.assertRaisesMessage(
            files.StorageError, "folder changed"
        ):
            trash.restore("incoming", operation["id"], self.actor, self.generation)
        self.assertFalse(self.archive.exists())
        self.assertFalse((retained_directory / "orphan.zip").exists())
        self.assertEqual(self.payload(operation).read_bytes(), b"retained archive bytes")

    def test_reference_appearing_after_review_protects_even_a_deleted_delivery(self):
        preview = self.preview()
        Delivery.objects.create(user=self.owner, filename="orphan.zip", size_bytes=22, is_deleted=True)
        with self.assertRaises(files.StorageError):
            trash.quarantine("incoming", "alice/orphan.zip", self.actor, self.generation, preview["review_hash"])
        self.assertTrue(self.archive.exists())

    def test_known_job_artifacts_and_original_snapshots_remain_protected(self):
        artifact = self.job_directory / "report.pdf"
        artifact.write_bytes(b"report")
        delivery = Delivery.objects.create(user=self.owner, filename="other.zip", size_bytes=1)
        Job.objects.create(job_uuid=self.job_id, delivery=delivery, product_ident="test", product_description="Test")
        relative = self.job_directory.name + "/report.pdf"
        preview = trash.preview_quarantine("jobs", relative, self.actor)
        self.assertFalse(preview["can_quarantine"])
        with self.assertRaises(files.StorageError):
            trash.quarantine("jobs", relative, self.actor, self.generation, preview["review_hash"])
        self.assertTrue(artifact.exists())

    def test_stale_generation_disabled_maintenance_and_transfer_pin_block_moves(self):
        preview = self.preview()
        for generation in (self.generation + 1, None, True, str(self.generation)):
            with self.subTest(generation=generation), self.assertRaises(files.StorageError):
                trash.quarantine("incoming", "alice/orphan.zip", self.actor, generation, preview["review_hash"])
        operation_id = str(uuid4())
        with file_lock("control"):
            pin_operation(operation_id, "export", self.generation)
        try:
            with self.assertRaises(files.StorageError):
                self.move()
        finally:
            with file_lock("control"):
                unpin_operation(operation_id)
        maintenance.disable(self.actor, self.generation)
        with self.assertRaises(files.StorageError):
            self.move()
        self.assertTrue(self.archive.exists())

    def test_busy_activity_and_transfer_execution_locks_block_moves(self):
        with file_lock("activity", exclusive=False):
            with self.assertRaises(files.StorageError):
                self.move()
        with store.execution_lock():
            with self.assertRaises(files.StorageError):
                self.move()
        self.assertTrue(self.archive.exists())

    def test_actor_must_remain_an_active_administrator(self):
        actor = get_user_model().objects.create_user("not-an-admin", password="test-password")
        with self.assertRaises(files.StorageError):
            trash.preview_quarantine("incoming", "alice/orphan.zip", actor)
        get_user_model().objects.filter(pk=self.actor.pk).update(is_active=False)
        with self.assertRaises(files.StorageError):
            self.move()
        self.assertTrue(self.archive.exists())

    def test_interrupted_move_after_rename_is_discoverable_and_restorable(self):
        write = trash._write
        def lose_completion(directory, journal):
            if journal["state"] == "quarantined":
                raise OSError("Injected lost completion")
            return write(directory, journal)
        with patch.object(trash, "_write", side_effect=lose_completion), self.assertRaises(files.StorageError):
            self.move()
        operation = trash.list_trash("incoming")["entries"][0]
        self.assertEqual(operation["state"], "moving")
        self.assertFalse(self.archive.exists())
        self.assertEqual(trash.restore("incoming", operation["id"], self.actor, self.generation)["state"], "restored")
        self.assertEqual(self.archive.read_bytes(), b"retained archive bytes")

    def test_interrupted_restore_after_link_resumes_without_overwrite_or_data_loss(self):
        operation = self.move()
        unlink = os.unlink
        def lose_cleanup(name, *args, **kwargs):
            if name == "payload":
                raise OSError("Injected lost cleanup")
            return unlink(name, *args, **kwargs)
        with patch.object(trash.os, "unlink", side_effect=lose_cleanup), self.assertRaises(files.StorageError):
            trash.restore("incoming", operation["id"], self.actor, self.generation)
        self.assertEqual(self.archive.stat().st_nlink, 2)
        self.assertEqual(trash.list_trash("incoming")["entries"][0]["state"], "restoring")
        self.assertEqual(trash.restore("incoming", operation["id"], self.actor, self.generation)["state"], "restored")
        self.assertEqual(self.archive.stat().st_nlink, 1)

    def test_trash_symlink_and_corrupt_journal_fail_closed(self):
        other = self.root / "outside-trash"
        other.mkdir()
        (self.incoming / files.TRASH_DIRECTORY).symlink_to(other, target_is_directory=True)
        with self.assertRaises(files.StorageError):
            self.move()
        self.assertTrue(self.archive.exists())
        (self.incoming / files.TRASH_DIRECTORY).unlink()
        operation = self.move()
        journal = self.payload(operation).parent / "journal.json"
        journal.write_text("broken journal")
        self.assertFalse(trash.list_trash("incoming")["entries"][0]["can_restore"])
        with self.assertRaises(files.StorageError):
            trash.restore("incoming", operation["id"], self.actor, self.generation)
        self.assertTrue(self.payload(operation).exists())
