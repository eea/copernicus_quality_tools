from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from qc_tool.frontend.dashboard.services.artifacts import ArtifactUnavailable
from qc_tool.frontend.dashboard.services.artifacts import open_regular_artifact
from qc_tool.frontend.dashboard.services.artifacts import read_text_artifact


class ArtifactFileTests(TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name) / "artifacts"
        self.root.mkdir()
        (self.root / "result.txt").write_text("safe", encoding="utf-8")

    def test_opens_a_direct_regular_file(self):
        with open_regular_artifact(self.root, "result.txt") as artifact:
            self.assertEqual(artifact.read(), b"safe")

    def test_rejects_traversal_and_nested_paths(self):
        for filename in ("..", "../outside.txt", "nested/file.txt", "..\\x"):
            with self.subTest(filename=filename):
                with self.assertRaises(ArtifactUnavailable):
                    open_regular_artifact(self.root, filename)

    def test_rejects_a_symbolic_link(self):
        outside = Path(self.temporary_directory.name) / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        (self.root / "link.txt").symlink_to(outside)

        with self.assertRaises(ArtifactUnavailable):
            open_regular_artifact(self.root, "link.txt")

    def test_text_reads_are_bounded(self):
        (self.root / "job.log").write_bytes(b"abcdefgh")

        result = read_text_artifact(self.root, "job.log", maximum_bytes=4)

        self.assertEqual(result, "abcd\n[log truncated]\n")
