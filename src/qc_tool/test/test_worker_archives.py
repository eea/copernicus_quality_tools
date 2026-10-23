"""Exercise the shared worker archive adapter without GDAL or PostgreSQL."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from zipfile import ZipFile

from qc_tool.worker.archives import do_unzip
from qc_tool.worker.status import CheckStatus


class WorkerArchiveTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="qc-worker-archive-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.destination = self.directory / "unpacked"
        self.status = CheckStatus()

    def write_archive(self, filename="delivery.ZIP"):
        path = self.directory / filename
        with ZipFile(path, "w") as archive:
            archive.writestr("nested/delivery.txt", b"original delivery")
        return path

    def test_extracts_nested_delivery_and_preserves_status_and_source(self):
        archive = self.write_archive()
        original = archive.read_bytes()

        do_unzip(archive, self.destination, self.status)

        self.assertEqual(self.status.status, "ok")
        self.assertEqual(self.status.params, {"unzip_dir": self.destination})
        self.assertEqual(self.status.status_properties["hash_files"], [archive.name])
        self.assertEqual((self.destination / "nested/delivery.txt").read_bytes(), b"original delivery")
        self.assertEqual(archive.read_bytes(), original)

    def test_wrong_extension_stops_before_creating_output(self):
        archive = self.write_archive("delivery.txt")

        do_unzip(archive, self.destination, self.status)

        self.assertEqual(self.status.status, "aborted")
        self.assertIn("Delivery must be a .zip file.", self.status.messages[0])
        self.assertFalse(self.destination.exists())
        self.assertFalse(self.status.params)
        self.assertFalse(self.status.status_properties)

    def test_invalid_archive_never_publishes_a_processing_directory(self):
        archive = self.directory / "broken.zip"
        archive.write_bytes(b"invalid archive")

        do_unzip(archive, self.destination, self.status)

        self.assertEqual(self.status.status, "aborted")
        self.assertIn("Error unzipping file broken.zip", self.status.messages[0])
        self.assertNotIn("unzip_dir", self.status.params)

    def test_existing_destination_is_preserved(self):
        archive = self.write_archive()
        self.destination.mkdir()
        existing = self.destination / "keep.txt"
        existing.write_bytes(b"existing data")

        do_unzip(archive, self.destination, self.status)

        self.assertEqual(self.status.status, "aborted")
        self.assertEqual(existing.read_bytes(), b"existing data")
        self.assertFalse((self.destination / "nested").exists())
        self.assertNotIn("unzip_dir", self.status.params)
