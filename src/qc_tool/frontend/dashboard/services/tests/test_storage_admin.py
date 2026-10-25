"""Filesystem administration is confined, reversible and maintenance guarded."""

from pathlib import Path
from hashlib import sha256
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile
import os

from django.conf import settings
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

    def test_work_browser_opens_arbitrary_normal_folders_without_sql_or_job_layout(self):
        directory = self.work / "operator-reports" / "October"
        directory.mkdir(parents=True)
        original = directory / "notes.txt"
        original.write_bytes(b"retained operator notes")
        (self.work / "frontend.log").write_bytes(b"application log")
        listing = files.list_entries("work")
        self.assertIn("operator-reports", [entry["name"] for entry in listing["entries"]])
        self.assertIn("frontend.log", [entry["name"] for entry in listing["entries"]])
        self.assertTrue(listing["read_only"])
        self.assertFalse(listing["can_trash"])
        nested = files.list_entries("work", "operator-reports/October")
        self.assertEqual(nested["parent_path"], "operator-reports")
        self.assertEqual((nested["folder_count"], nested["file_count"], nested["visible_bytes"]),
                         (0, 1, len(original.read_bytes())))
        with files.open_file("work", "operator-reports/October/notes.txt") as stream:
            self.assertEqual(stream.read(), b"retained operator notes")
        self.assertTrue(files.quarantine_reason("work", "operator-reports/October/notes.txt",
                                               files.inspect_entry("work", "operator-reports/October/notes.txt")))
        self.assertIsNone(files.list_entries("work")["parent_path"])

    def test_physical_locations_show_real_root_names_and_paths_without_a_virtual_job_location(self):
        uploaded = self.work / "product_definitions"
        installed = self.root / "installed-products"
        for directory in (uploaded, installed):
            directory.mkdir()
        with patch.dict(CONFIG, product_dirs=[installed]):
            areas = {area["key"]: area for area in files.storage_areas()}
            locations = {location["key"]: location for location in files.storage_locations()}
            self.assertNotIn("jobs", locations)
            expected = {"work": self.work, "incoming": self.incoming, "published": self.published,
                        "boundaries": self.boundaries, "spec-0": installed}
            self.assertEqual(set(locations), set(expected))
            for area, directory in expected.items():
                with self.subTest(area=area):
                    location = locations[area]
                    self.assertEqual(location["label"], directory.name)
                    self.assertTrue(location["purpose_label"])
                    self.assertEqual(location["storage_path"], str(directory))
                    self.assertTrue(location["available"])
                    self.assertNotIn("storage_path", files.area_info(area))
            self.assertNotIn(str(self.root), str(areas))

    def test_display_path_is_confined_to_a_configured_root_and_valid_relative_path(self):
        self.assertEqual(files.storage_path("work"), str(self.work))
        self.assertEqual(files.storage_path("work", "reports/October/notes.txt"),
                         str(self.work / "reports/October/notes.txt"))
        for path in ("../outside", "/etc/passwd", "reports/../../outside", "worker.token",
                     "maintenance/state.json", "product_definitions/.state/example.json"):
            with self.subTest(path=path), self.assertRaises(files.StorageError):
                files.storage_path("work", path)
        with self.assertRaises(files.StorageError):
            files.storage_path(str(self.work))

    def test_configured_and_uploaded_specifications_and_boundaries_remain_original_read_only_bytes(self):
        product_root = self.root / "deployed-products"
        product_root.mkdir()
        uploaded_root = self.work / "product_definitions"
        uploaded_root.mkdir()
        original = b'{ "untouched": "original bytes" }\n'
        for root in (product_root, uploaded_root, self.boundaries):
            (root / "original.json").write_bytes(original)
        with patch.dict(CONFIG, product_dirs=[product_root]):
            areas = {area["key"]: area for area in files.storage_areas()}
            for area in ("spec-0", "uploaded-specifications", "boundaries"):
                self.assertTrue(areas[area]["available"])
                self.assertTrue(areas[area]["read_only"])
                self.assertFalse(areas[area]["can_trash"])
                entry = files.inspect_entry(area, "original.json")
                self.assertTrue(files.quarantine_reason(area, "original.json", entry))
                with files.open_file(area, "original.json") as stream:
                    self.assertEqual(stream.read(), original)
            self.assertNotIn(str(self.root), str(areas))
            self.assertNotIn("root", files.area_info("spec-0"))
            with self.assertRaises(files.StorageError):
                files.open_file("spec-1", "original.json")
        for root in (product_root, uploaded_root, self.boundaries):
            self.assertEqual((root / "original.json").read_bytes(), original)

    def test_general_work_browser_hides_private_children_and_refuses_direct_downloads(self):
        for name in ("maintenance", "data-transfer", "s3_credentials"):
            directory = self.work / name
            directory.mkdir()
            (directory / "secret.json").write_text("private")
        (self.work / "worker.token").write_text("private")
        ordinary = self.work / "normal" / "nested"
        ordinary.mkdir(parents=True)
        private = ordinary / "custom-control"
        private.mkdir()
        (private / "state.json").write_text("private state")
        with override_settings(QC_TOOL_MAINTENANCE_DIR=private):
            listing = files.list_entries("work")
            self.assertFalse({"maintenance", "data-transfer", "s3_credentials", "worker.token"}
                             & {entry["name"] for entry in listing["entries"]})
            self.assertEqual(listing["skipped_count"], 4)
            self.assertEqual(files.list_entries("work", "normal/nested")["entries"], [])
            for path in ("worker.token", "maintenance/secret.json", "data-transfer/secret.json",
                         "s3_credentials/secret.json", "normal/nested/custom-control/state.json"):
                with self.subTest(path=path), self.assertRaises(files.StorageError):
                    files.open_file("work", path)
            with self.assertRaises(files.StorageError):
                files.list_entries("work", "normal/nested/custom-control")

    def test_database_private_upload_staging_and_tls_files_are_not_normal_work_files(self):
        database = self.work / "frontend.sqlite3"
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(database) + suffix).write_bytes(b"private database")
        staging = self.work / "upload-staging"
        staging.mkdir()
        (staging / "part.zip").write_bytes(b"private multipart upload")
        key = self.work / "client.key"
        key.write_bytes(b"private client key")
        with patch.dict(CONFIG, frontend_db_path=database), override_settings(FILE_UPLOAD_TEMP_DIR=staging):
            with patch.dict(settings.DATABASES["default"].setdefault("OPTIONS", {}), sslkey=str(key)):
                listing = files.list_entries("work")
                self.assertFalse({"frontend.sqlite3", "frontend.sqlite3-wal", "frontend.sqlite3-shm",
                                  "frontend.sqlite3-journal", "upload-staging", "client.key"}
                                 & {entry["name"] for entry in listing["entries"]})
                for path in ("frontend.sqlite3", "frontend.sqlite3-wal", "client.key", "upload-staging/part.zip"):
                    with self.subTest(path=path), self.assertRaises(files.StorageError):
                        files.open_file("work", path)

    def test_browse_sort_keeps_folders_first_and_reports_filtered_totals(self):
        (self.work / "z-folder").mkdir()
        (self.work / "a.txt").write_bytes(b"a")
        (self.work / "b.txt").write_bytes(b"bbbb")
        os.utime(self.work / "a.txt", (1000, 1000))
        os.utime(self.work / "b.txt", (2000, 2000))
        for sort in ("name", "size", "modified"):
            with self.subTest(sort=sort):
                listing = files.list_entries("work", sort=sort, descending=True)
                self.assertEqual([row["kind"] for row in listing["entries"][:2]], ["directory", "directory"])
                self.assertEqual([row["name"] for row in listing["entries"][2:]], ["b.txt", "a.txt"])
        listing = files.list_entries("work", query=".txt", page_size=1)
        self.assertEqual((listing["total"], listing["file_count"], listing["folder_count"], listing["visible_bytes"]),
                         (2, 2, 0, 5))
        self.assertTrue(listing["has_next"])
        self.assertEqual(files.list_entries("work", sort="unsupported")["sort"], "name")

    def test_new_roots_cannot_be_repointed_to_private_storage_or_broader_work_root(self):
        for key in ("boundary_dir", "product_dirs"):
            configured = {key: [self.work] if key == "product_dirs" else self.work}
            with patch.dict(CONFIG, **configured), self.assertRaises(files.StorageError):
                files.list_entries("spec-0" if key == "product_dirs" else "boundaries")
        private = self.root / "private"
        private.mkdir()
        with patch.dict(CONFIG, boundary_dir=private), override_settings(QC_TOOL_TRANSFER_DIR=private):
            with self.assertRaises(files.StorageError):
                files.list_entries("boundaries")
        with override_settings(S3_CREDENTIALS_DIR=self.work):
            with self.assertRaises(files.StorageError):
                files.list_entries("work")

    def test_missing_mount_has_recoverable_area_metadata(self):
        with patch.dict(CONFIG, boundary_dir=self.root / "missing-boundaries"):
            area = next(area for area in files.storage_areas() if area["key"] == "boundaries")
        self.assertFalse(area["available"])
        self.assertTrue(area["message"])
        self.assertIn("boundary", area["description"])

    def test_boundary_generation_content_can_be_browsed_without_following_activation_links(self):
        relative = ".boundary-generations/gen-" + "a" * 32 + "/vector/original.gpkg"
        original = self.boundaries / relative
        original.parent.mkdir(parents=True)
        original.write_bytes(b"original immutable boundary bytes")
        (self.boundaries / ".boundary-package.lock").write_bytes(b"private lock")
        (self.boundaries / ".boundary-current").symlink_to(".boundary-generations/gen-" + "a" * 32)
        (self.boundaries / "vector").symlink_to(".boundary-current/vector")
        listing = files.list_entries("boundaries")
        self.assertEqual([entry["name"] for entry in listing["entries"]], [".boundary-generations"])
        self.assertEqual(listing["skipped_count"], 3)
        nested = files.list_entries("boundaries", relative.rpartition("/")[0])
        self.assertEqual([entry["name"] for entry in nested["entries"]], ["original.gpkg"])
        with files.open_file("boundaries", relative) as stream:
            self.assertEqual(stream.read(), b"original immutable boundary bytes")
        for path in (".boundary-current/vector/original.gpkg", "vector/original.gpkg", ".boundary-package.lock"):
            with self.subTest(path=path), self.assertRaises(files.StorageError):
                files.open_file("boundaries", path)
        self.assertEqual(original.read_bytes(), b"original immutable boundary bytes")

    def test_uploaded_specification_versions_open_with_state_and_locks_still_hidden(self):
        uploaded = self.work / "product_definitions"
        relative = ".versions/example-product/" + "b" * 64 + ".json"
        original = uploaded / relative
        original.parent.mkdir(parents=True)
        original.write_bytes(b'{ "unchanged": "original specification" }\n')
        (uploaded / ".state").mkdir()
        (uploaded / ".state/example-product.json").write_bytes(b"private activation state")
        (uploaded / ".upload.lock").write_bytes(b"private lock")
        self.assertEqual([entry["name"] for entry in files.list_entries("uploaded-specifications")["entries"]], [".versions"])
        self.assertEqual(files.list_entries("uploaded-specifications", ".versions/example-product")["entries"][0]["path"], relative)
        with files.open_file("uploaded-specifications", relative) as stream:
            self.assertEqual(stream.read(), b'{ "unchanged": "original specification" }\n')
        for path in (".state/example-product.json", ".upload.lock", ".versions/example-product/.private.json"):
            with self.subTest(path=path), self.assertRaises(files.StorageError):
                files.open_file("uploaded-specifications", path)
        self.assertEqual(original.read_bytes(), b'{ "unchanged": "original specification" }\n')

    def test_content_namespace_exceptions_do_not_enable_other_hidden_paths_or_unsafe_links(self):
        uploaded = self.work / "product_definitions"
        uploaded.mkdir()
        for area, root, name in (("boundaries", self.boundaries, ".boundary-generations"),
                                  ("uploaded-specifications", uploaded, ".versions")):
            (root / name).write_bytes(b"this namespace must be a directory")
            with self.subTest(area=area):
                self.assertEqual(files.list_entries(area)["entries"], [])
                with self.assertRaises(files.StorageError):
                    files.open_file(area, name)
            (root / name).unlink()
            (root / name).symlink_to(self.owner_directory, target_is_directory=True)
            with self.subTest(area=area):
                self.assertEqual(files.list_entries(area)["entries"], [])
                with self.assertRaises(files.StorageError):
                    files.list_entries(area, name)
        for area, path in (("work", ".versions"), ("work", ".boundary-generations"),
                           ("incoming", ".versions"), ("published", ".boundary-generations"),
                           ("boundaries", ".versions"), ("uploaded-specifications", ".boundary-generations")):
            with self.subTest(area=area, path=path), self.assertRaises(files.StorageError):
                files.list_entries(area, path)

    def test_canonical_originals_are_accessible_through_work_and_extra_root_folder_paths(self):
        from qc_tool.frontend.dashboard.services.storage_admin import downloads

        uploaded = self.work / "product_definitions"
        boundary_parent = self.work / "geodata"
        boundaries = boundary_parent / "boundaries"
        spec_relative = ".versions/example/" + "c" * 64 + ".json"
        boundary_relative = ".boundary-generations/gen-" + "d" * 32 + "/vector/original.gpkg"
        spec_file = uploaded / spec_relative
        boundary_file = boundaries / boundary_relative
        spec_bytes = b'{ "preserved": "original specification bytes" }\n'
        boundary_bytes = b"original immutable boundary bytes\x00\xff"
        for original, payload in ((spec_file, spec_bytes), (boundary_file, boundary_bytes)):
            original.parent.mkdir(parents=True)
            original.write_bytes(payload)
            (original.parent / ".private-state").write_bytes(b"private nested state")
        configured = [{"key": "spec-originals", "label": "Saved specifications", "path": str(uploaded)},
                      {"key": "geodata", "label": "Geospatial storage", "path": str(boundary_parent)}]
        with patch.dict(CONFIG, boundary_dir=boundaries), override_settings(QC_TOOL_STORAGE_ROOTS=configured):
            aliases = (("uploaded-specifications", spec_relative, spec_bytes),
                       ("work", "product_definitions/" + spec_relative, spec_bytes),
                       ("extra-spec-originals", spec_relative, spec_bytes),
                       ("boundaries", boundary_relative, boundary_bytes),
                       ("work", "geodata/boundaries/" + boundary_relative, boundary_bytes),
                       ("extra-geodata", "boundaries/" + boundary_relative, boundary_bytes))
            for area, relative, payload in aliases:
                with self.subTest(area=area, relative=relative):
                    parent = relative.rpartition("/")[0]
                    listing = files.list_entries(area, parent)
                    self.assertEqual([row["path"] for row in listing["entries"]], [relative])
                    self.assertEqual(listing["skipped_count"], 1)
                    self.assertEqual(files.inspect_entry(area, relative)["size_bytes"], len(payload))
                    with files.open_file(area, relative) as stream:
                        self.assertEqual(stream.read(), payload)
                    plan = downloads.prepare_zip(area, [parent])
                    self.assertEqual(plan.file_count, 1)
                    self.assertEqual(plan.excluded_count, 1)
                    with ZipFile(BytesIO(b"".join(downloads.stream_zip(plan)))) as archive:
                        self.assertEqual(archive.read("files/" + relative), payload)
                        self.assertIsNone(archive.testzip())
        self.assertEqual(spec_file.read_bytes(), spec_bytes)
        self.assertEqual(boundary_file.read_bytes(), boundary_bytes)

    def test_content_namespace_permission_does_not_follow_same_named_folders_elsewhere(self):
        from qc_tool.frontend.dashboard.services.storage_admin import downloads

        fake = self.work / "operator-files"
        for namespace in (".versions", ".boundary-generations"):
            original = fake / namespace / "retained/original.bin"
            original.parent.mkdir(parents=True)
            original.write_bytes(b"hidden unrelated content")
        configured = [{"key": "operator-files", "label": "Operator files", "path": str(fake)}]
        with override_settings(QC_TOOL_STORAGE_ROOTS=configured):
            for area, prefix in (("work", "operator-files/"), ("extra-operator-files", "")):
                self.assertEqual(files.list_entries(area, prefix.rstrip("/"))["entries"], [])
                for namespace in (".versions", ".boundary-generations"):
                    relative = prefix + namespace + "/retained/original.bin"
                    for action in (files.inspect_entry, files.open_file):
                        with self.subTest(area=area, relative=relative, action=action.__name__), self.assertRaises(files.StorageError):
                            action(area, relative)
                    with self.subTest(area=area, relative=relative), self.assertRaises(files.StorageError):
                        downloads.prepare_zip(area, [relative])

    def test_direct_configured_roots_cannot_bypass_private_specification_or_boundary_controls(self):
        uploaded = self.work / "product_definitions"
        controls = (uploaded / ".state", uploaded / ".upload.lock",
                    self.boundaries / ".boundary-current", self.boundaries / ".boundary-package.lock")
        for control in controls:
            control.mkdir(parents=True)
            (control / "secret.json").write_bytes(b"private application control")
        for control in controls:
            with self.subTest(control=control.name), patch.dict(CONFIG, product_dirs=[control]), override_settings(
                QC_TOOL_STORAGE_ROOTS=[{"key": "unsafe", "label": "Unsafe alias", "path": str(control)}]
            ):
                for area in ("spec-0", "extra-unsafe"):
                    with self.subTest(area=area), self.assertRaises(files.StorageError):
                        files.list_entries(area)
                    with self.subTest(area=area), self.assertRaises(files.StorageError):
                        files.open_file(area, "secret.json")
        self.assertTrue(all((control / "secret.json").read_bytes() == b"private application control"
                            for control in controls))

    def test_folder_zip_uses_same_content_visibility_and_keeps_runtime_controls_excluded(self):
        from qc_tool.frontend.dashboard.services.storage_admin import downloads

        uploaded = self.work / "product_definitions"
        uploaded.mkdir()
        for area, root, namespace in (("boundaries", self.boundaries, ".boundary-generations"),
                                     ("uploaded-specifications", uploaded, ".versions")):
            relative = namespace + "/retained/original.bin"
            original = root / relative
            original.parent.mkdir(parents=True)
            original.write_bytes(b"original retained content")
            (root / ".private-control").write_bytes(b"private control bytes")
            (original.parent / ".private-state").write_bytes(b"private nested state")
            with self.subTest(area=area):
                plan = downloads.prepare_zip(area, [""])
                self.assertEqual({entry.path for entry in plan.entries if entry.kind == "file"}, {relative})
                self.assertEqual(plan.excluded_count, 2)
                zipped = b"".join(downloads.stream_zip(plan))
                self.assertNotIn(b"private control bytes", zipped)
                self.assertNotIn(b"private nested state", zipped)
                with ZipFile(BytesIO(zipped)) as archive:
                    self.assertEqual(archive.read("files/" + relative), b"original retained content")
                    self.assertIsNone(archive.testzip())
                with self.assertRaises(files.StorageError):
                    downloads.prepare_zip(area, [".private-control"])

    def test_extra_roots_are_operator_configured_read_only_and_cannot_be_selected_by_path(self):
        mounted = self.root / "operator-mounted-data"
        mounted.mkdir()
        (mounted / "sample.bin").write_bytes(b"external configured mount")
        configured = [{"key": "project-data", "label": "Project files", "path": str(mounted)}]
        with override_settings(QC_TOOL_STORAGE_ROOTS=configured):
            info = files.area_info("extra-project-data")
            self.assertEqual(info["label"], "Project files")
            self.assertTrue(info["read_only"])
            self.assertFalse(info["can_trash"])
            self.assertEqual(files.list_entries("extra-project-data")["file_count"], 1)
            with files.open_file("extra-project-data", "sample.bin") as stream:
                self.assertEqual(stream.read(), b"external configured mount")
            with self.assertRaises(files.StorageError):
                files.list_entries(str(mounted))
        with self.assertRaises(files.StorageError):
            files.list_entries("extra-project-data")

    def test_extra_root_configuration_rejects_duplicate_keys_relative_paths_and_private_overlap(self):
        for configured in ([{"key": "../bad", "label": "Bad", "path": str(self.root)}],
                           [{"key": "relative", "label": "Bad", "path": "relative"}],
                           [{"key": "same", "label": "One", "path": str(self.root)}] * 2):
            with override_settings(QC_TOOL_STORAGE_ROOTS=configured), self.assertRaises(files.StorageError):
                files.storage_areas()
        with override_settings(QC_TOOL_STORAGE_ROOTS=[
                {"key": "private", "label": "Private", "path": str(self.root / "transfers")}]):
            with self.assertRaises(files.StorageError):
                files.list_entries("extra-private")

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

    def test_new_read_only_areas_reject_even_direct_quarantine_requests_without_creating_trash(self):
        uploaded = self.work / "product_definitions"
        uploaded.mkdir()
        specs = self.root / "specifications"
        specs.mkdir()
        extra = self.root / "extra"
        extra.mkdir()
        with patch.dict(CONFIG, product_dirs=[specs]), override_settings(QC_TOOL_STORAGE_ROOTS=[
                {"key": "archive", "label": "Archive", "path": str(extra)}]):
            for area, directory in (("work", self.work), ("boundaries", self.boundaries),
                                    ("uploaded-specifications", uploaded), ("spec-0", specs),
                                    ("extra-archive", extra)):
                original = directory / "unlinked.zip"
                original.write_bytes(b"unchanged original")
                with self.subTest(area=area), self.assertRaisesMessage(files.StorageError, "browsing and downloading"):
                    trash.quarantine(area, "unlinked.zip", self.actor, self.generation, "")
                self.assertEqual(original.read_bytes(), b"unchanged original")
                self.assertFalse((directory / files.TRASH_DIRECTORY).exists())

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
