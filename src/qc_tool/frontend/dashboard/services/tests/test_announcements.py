from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from qc_tool.frontend.dashboard.services.configuration import AnnouncementStorageError
from qc_tool.frontend.dashboard.services.configuration import read_announcement
from qc_tool.frontend.dashboard.services.configuration import write_announcement


class AnnouncementStorageTests(TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.path = self.root / "announcement.txt"

    def test_round_trips_a_bounded_utf8_message(self):
        write_announcement(self.path, "Scheduled maintenance — 18:00")

        self.assertEqual(
            read_announcement(self.path),
            "Scheduled maintenance — 18:00",
        )
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_missing_message_is_empty(self):
        self.assertEqual(read_announcement(self.path), "")

    def test_rejects_a_symbolic_link_without_touching_its_target(self):
        outside = self.root / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        self.path.symlink_to(outside)

        with self.assertRaises(AnnouncementStorageError):
            write_announcement(self.path, "replacement")
        with self.assertRaises(AnnouncementStorageError):
            read_announcement(self.path)

        self.assertEqual(outside.read_text(encoding="utf-8"), "secret")

