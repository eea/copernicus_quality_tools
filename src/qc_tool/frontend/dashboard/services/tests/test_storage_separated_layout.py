"""Physical specification libraries follow configured roots without private aliases."""

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from qc_tool.common import CONFIG
from qc_tool.frontend.dashboard.services.storage_admin import files


class SeparatedStorageBrowserTests(SimpleTestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.data = self.root / "data"
        self.specifications = self.data / "specifications"
        self.work = self.data / "jobs"
        self.private = self.root / "private"
        self.shared = self.root / "shared"
        self.logs = self.root / "logs"
        self.scratch = self.root / "scratch"
        self.incoming = self.data / "incoming"
        self.boundaries = self.data / "boundaries"
        self.submissions = self.data / "submissions"
        for path in (self.work, self.specifications, self.private, self.shared, self.logs,
                     self.scratch, self.incoming, self.boundaries, self.submissions):
            path.mkdir(parents=True, exist_ok=True)
        self.enterContext(patch.dict(CONFIG, data_root=self.data, work_dir=self.work,
            specifications_dir=self.specifications, frontend_state_dir=self.private,
            shared_state_dir=self.shared, log_dir=self.logs, scratch_dir=self.scratch,
            incoming_dir=self.incoming, boundary_dir=self.boundaries, submission_dir=self.submissions,
            product_dirs=[]))
        self.enterContext(override_settings(MEDIA_ROOT=self.incoming, QC_TOOL_STORAGE_ROOTS=[],
            QC_TOOL_PERSISTENT_STORAGE_ROOT="", QC_TOOL_PERSISTENT_STORAGE_ID="",
            QC_TOOL_MAINTENANCE_DIR=self.shared / "maintenance", QC_TOOL_TRANSFER_DIR=self.private / "transfers",
            S3_CREDENTIALS_DIR=self.private / "credentials", FILE_UPLOAD_TEMP_DIR=self.private / "upload-temp"))
        self.original = b'{\n  "description": "Original specification", "steps": []\n}\n'
        self.relative = ".versions/example/" + sha256(self.original).hexdigest() + ".json"
        path = self.specifications / self.relative
        path.parent.mkdir(parents=True)
        path.write_bytes(self.original)
        (self.specifications / ".state").mkdir()
        (self.specifications / ".state/example.json").write_bytes(b"private activation")

    def test_originals_use_canonical_mount_and_private_aliases_fail_closed(self):
        self.assertEqual(files._areas()["uploaded-specifications"]["root"], self.specifications)
        with files.open_file("uploaded-specifications", self.relative) as stream:
            self.assertEqual(stream.read(), self.original)
        with self.assertRaises(files.StorageError):
            files.open_file("uploaded-specifications", ".state/example.json")
        self.assertFalse((self.work / "product_definitions").exists())
        for key, path in (("frontend", self.private), ("shared", self.shared),
                          ("logs", self.logs), ("scratch", self.scratch)):
            with self.subTest(key=key), override_settings(QC_TOOL_STORAGE_ROOTS=[{
                "key": key, "label": key, "path": str(path),
            }]), self.assertRaises(files.StorageError):
                files.list_entries("extra-" + key)

    def test_explicit_legacy_configuration_keeps_original_work_subdirectory(self):
        legacy = self.work / "product_definitions" / self.relative
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(self.original)
        with patch.dict(CONFIG, data_root=None, specifications_dir=None, shared_state_dir=None,
                        frontend_state_dir=None, log_dir=None, scratch_dir=None):
            self.assertEqual(files._areas()["uploaded-specifications"]["root"], self.work / "product_definitions")
            with files.open_file("uploaded-specifications", self.relative) as stream:
                self.assertEqual(stream.read(), self.original)
        self.assertEqual((self.specifications / self.relative).read_bytes(), self.original)
