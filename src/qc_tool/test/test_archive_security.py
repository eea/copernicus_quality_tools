import stat
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from zipfile import ZIP_DEFLATED
from zipfile import ZipFile
from zipfile import ZipInfo

from qc_tool.archive_security import ArchiveLimits
from qc_tool.archive_security import safely_extract_zip
from qc_tool.archive_security import UnsafeArchiveError


class SafeZipExtractionTests(TestCase):
    """Untrusted archives must be validated before any payload is published."""

    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.archive = self.root / "delivery.zip"
        self.destination = self.root / "extracted"

    def write_archive(self, members, *, compression=ZIP_DEFLATED):
        with ZipFile(self.archive, "w", compression=compression) as archive:
            for name, payload in members:
                archive.writestr(name, payload)

    def assert_rejected_without_output(self, limits=None):
        with self.assertRaises(UnsafeArchiveError):
            safely_extract_zip(self.archive, self.destination, limits=limits)
        self.assertFalse(self.destination.exists())

    def test_extracts_a_valid_nested_archive(self):
        self.write_archive(
            (("metadata.xml", b"<metadata />"), ("data/layer.csv", b"id\n1\n"))
        )

        result = safely_extract_zip(self.archive, self.destination)

        self.assertEqual(result, self.destination)
        self.assertEqual(
            (self.destination / "data" / "layer.csv").read_bytes(),
            b"id\n1\n",
        )

    def test_rejects_parent_traversal(self):
        self.write_archive((("../outside.txt", b"unsafe"),))

        self.assert_rejected_without_output()
        self.assertFalse((self.root / "outside.txt").exists())

    def test_rejects_links_and_special_entries(self):
        link = ZipInfo("payload-link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with ZipFile(self.archive, "w") as archive:
            archive.writestr(link, "outside")

        self.assert_rejected_without_output()

    def test_rejects_case_or_unicode_normalized_duplicates(self):
        self.write_archive((("DATA.csv", b"one"), ("data.csv", b"two")))

        self.assert_rejected_without_output()

    def test_rejects_excessive_compression_ratio(self):
        self.write_archive((("zeros.bin", b"0" * 32_000),))
        limits = ArchiveLimits(
            max_archive_bytes=100_000,
            max_members=10,
            max_member_bytes=100_000,
            max_uncompressed_bytes=100_000,
            max_compression_ratio=2,
            max_path_bytes=1_024,
            max_component_bytes=255,
            max_path_depth=10,
        )

        self.assert_rejected_without_output(limits)

    def test_never_overwrites_an_existing_destination(self):
        self.write_archive((("payload.txt", b"safe"),))
        self.destination.mkdir()
        marker = self.destination / "keep.txt"
        marker.write_text("keep", encoding="utf-8")

        with self.assertRaises(UnsafeArchiveError):
            safely_extract_zip(self.archive, self.destination)

        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

