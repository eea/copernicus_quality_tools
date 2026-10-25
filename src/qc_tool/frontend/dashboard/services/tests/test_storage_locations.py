"""Browser locations follow physical roots without changing file ownership."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from qc_tool.common import CONFIG, locate_product_definition
from qc_tool.frontend.dashboard.services.storage_admin import files


class StorageLocationsTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.root = Path(self.enterContext(TemporaryDirectory(prefix="qc-storage-locations-")))
        self.work = self.root / "work"
        self.incoming = self.root / "incoming"
        self.published = self.root / "published"
        self.boundaries = self.root / "boundaries"
        self.uploaded = self.work / "product_definitions"
        for directory in (self.work, self.incoming, self.published, self.boundaries):
            directory.mkdir()
        self.enterContext(patch.dict(CONFIG, work_dir=self.work, incoming_dir=self.incoming,
            submission_dir=self.published, boundary_dir=self.boundaries, product_dirs=[]))
        self.enterContext(override_settings(MEDIA_ROOT=self.incoming, QC_TOOL_STORAGE_ROOTS=[],
            S3_CREDENTIALS_DIR=self.root / "credentials",
            QC_TOOL_MAINTENANCE_DIR=self.root / "maintenance",
            QC_TOOL_TRANSFER_DIR=self.root / "transfers"))

    def locations(self):
        return {item["key"]: item for item in files.storage_locations()}

    def test_uploaded_specifications_are_a_real_child_of_work_instead_of_another_root(self):
        self.uploaded.mkdir()
        original = b'{ "description": "Original specification", "steps": [] }\n'
        (self.uploaded / "example.json").write_bytes(original)

        locations = self.locations()

        self.assertIn("work", locations)
        self.assertNotIn("jobs", locations)
        self.assertNotIn("uploaded-specifications", locations)
        self.assertIn("product_definitions", [entry["name"] for entry in files.list_entries("work")["entries"]])
        self.assertEqual(files.storage_path("work", "product_definitions"), str(self.uploaded))
        self.assertEqual(files.list_entries("work", "product_definitions")["entries"][0]["name"], "example.json")
        with files.open_file("uploaded-specifications", "example.json") as stream:
            self.assertEqual(stream.read(), original)
        with files.open_file("work", "product_definitions/example.json") as stream:
            self.assertEqual(stream.read(), original)

    def test_external_specifications_are_a_separate_real_root_and_duplicate_aliases_are_not_locations(self):
        installed = self.root / "installed" / "product_definitions"
        installed.mkdir(parents=True)
        with patch.dict(CONFIG, product_dirs=[installed, installed]):
            locations = self.locations()
            roots = [item for item in locations.values() if item["storage_path"] == str(installed)]

            self.assertEqual(len(roots), 1)
            self.assertEqual(roots[0]["label"], "product_definitions")
            self.assertEqual(roots[0]["group"], "installation")
            self.assertTrue(roots[0]["read_only"])
            self.assertFalse(roots[0]["can_trash"])
            self.assertEqual({item["key"] for item in files.storage_areas()} & {"spec-0", "spec-1"},
                             {"spec-0", "spec-1"})

    def test_nested_read_only_roots_do_not_create_duplicate_folder_trees(self):
        external = self.root / "external-storage"
        nested = external / "retained" / "reports"
        nested.mkdir(parents=True)
        extra = [
            {"key": "reports", "label": "Reports", "path": nested},
            {"key": "external", "label": "External storage", "path": external},
        ]
        with override_settings(QC_TOOL_STORAGE_ROOTS=extra):
            locations = self.locations()

            self.assertIn("extra-external", locations)
            self.assertNotIn("extra-reports", locations)
            self.assertEqual(files.list_entries("extra-reports")["entries"], [])
            self.assertEqual(files.list_entries("extra-external", "retained/reports")["entries"], [])

    def test_installed_source_inside_data_storage_keeps_its_installation_ownership(self):
        installed = self.work / "installation-source"
        installed.mkdir()
        with patch.dict(CONFIG, product_dirs=[installed]):
            locations = self.locations()

            self.assertIn("work", locations)
            self.assertIn("spec-0", locations)
            self.assertEqual(locations["work"]["group"], "storage")
            self.assertEqual(locations["spec-0"]["group"], "installation")

    def test_configured_child_that_parent_cannot_browse_keeps_its_own_location(self):
        external = self.root / "external"
        hidden = external / ".retained"
        hidden.mkdir(parents=True)
        extra = [
            {"key": "external", "label": "External", "path": external},
            {"key": "retained", "label": "Retained", "path": hidden},
        ]
        with override_settings(QC_TOOL_STORAGE_ROOTS=extra):
            locations = self.locations()

            self.assertTrue(locations["extra-external"]["available"])
            self.assertTrue(locations["extra-retained"]["available"])
            self.assertEqual(files.list_entries("extra-retained")["entries"], [])
            with self.assertRaises(files.StorageError):
                files.list_entries("extra-external", ".retained")

    def test_nested_delivery_root_retains_its_narrow_trash_policy(self):
        nested = self.work / "incoming"
        nested.mkdir()
        (nested / "orphan.zip").write_bytes(b"archive")
        with override_settings(MEDIA_ROOT=nested):
            locations = self.locations()

            self.assertIn("work", locations)
            self.assertIn("incoming", locations)
            self.assertTrue(locations["work"]["read_only"])
            self.assertFalse(locations["work"]["can_trash"])
            self.assertFalse(locations["incoming"]["read_only"])
            self.assertTrue(locations["incoming"]["can_trash"])
            writable = files.inspect_entry("incoming", "orphan.zip")
            readonly = files.inspect_entry("work", "incoming/orphan.zip")
            self.assertEqual(files.quarantine_reason("incoming", "orphan.zip", writable), "")
            self.assertTrue(files.quarantine_reason("work", "incoming/orphan.zip", readonly))

    def test_missing_external_root_stays_discoverable_without_creating_storage(self):
        missing = self.root / "not-mounted" / "product_definitions"
        with patch.dict(CONFIG, product_dirs=[missing]):
            locations = self.locations()

            self.assertIn("spec-0", locations)
            self.assertFalse(locations["spec-0"]["available"])
            self.assertTrue(locations["spec-0"]["message"])
            self.assertEqual(locations["spec-0"]["storage_path"], str(missing))
            self.assertFalse(missing.exists())
            self.assertFalse(self.uploaded.exists())

    def test_missing_nested_root_is_not_hidden_by_its_available_parent(self):
        self.assertFalse(self.uploaded.exists())

        locations = self.locations()

        self.assertTrue(locations["work"]["available"])
        self.assertFalse(locations["uploaded-specifications"]["available"])
        self.assertEqual(locations["uploaded-specifications"]["storage_path"], str(self.uploaded))
        self.assertFalse(self.uploaded.exists())

    def test_unavailable_symlink_alias_cannot_make_the_real_source_writable(self):
        installed = self.root / "installed"
        installed.mkdir()
        (installed / "example.json").write_bytes(b"original bytes")
        linked = self.root / "installed-link"
        linked.symlink_to(installed, target_is_directory=True)
        with patch.dict(CONFIG, product_dirs=[installed, linked]):
            self.locations()
            areas = {area["key"]: area for area in files.storage_areas()}

            self.assertTrue(areas["spec-0"]["available"])
            self.assertFalse(areas["spec-1"]["available"])
            self.assertTrue(areas["spec-0"]["read_only"])
            with self.assertRaises(files.StorageError):
                files.open_file("spec-1", "example.json")
            self.assertEqual((installed / "example.json").read_bytes(), b"original bytes")

    def test_inventory_does_not_change_qc_source_precedence_or_original_bytes(self):
        first, second = self.root / "first", self.root / "second"
        for directory in (first, second, self.uploaded):
            directory.mkdir(parents=True)
        originals = {
            first: b'{ "description": "First", "steps": [] }\n',
            second: b'{ "description": "Second", "steps": [] }\n',
            self.uploaded: b'{ "description": "Legacy uploaded", "steps": [] }\n',
        }
        for directory, payload in originals.items():
            (directory / "example.json").write_bytes(payload)
        with patch.dict(CONFIG, product_dirs=[first, second, first]):
            before = locate_product_definition("example")
            self.locations()

            self.assertEqual(locate_product_definition("example"), before)
            self.assertEqual(before, first / "example.json")
            for key, directory in (("spec-0", first), ("spec-1", second),
                                   ("spec-2", first), ("uploaded-specifications", self.uploaded)):
                with self.subTest(area=key), files.open_file(key, "example.json") as stream:
                    self.assertEqual(stream.read(), originals[directory])
            self.assertFalse((self.uploaded / ".state").exists())
            self.assertFalse((self.uploaded / ".versions").exists())
