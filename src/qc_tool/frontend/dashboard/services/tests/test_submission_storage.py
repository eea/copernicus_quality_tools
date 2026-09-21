"""Retained receipt locators remain safe and portable between storage roots."""

from pathlib import Path
import tempfile

from django.test import SimpleTestCase

from qc_tool.frontend.dashboard.services.submissions.storage import (
    artifact_directory,
    artifact_key_for_directory,
    validate_artifact_key,
)


class ArtifactKeyTests(SimpleTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def test_ambiguous_or_escaping_keys_are_rejected(self):
        for key in (
            "", "/absolute/path", "../outside", "safe/../../outside", "safe/../inside",
            "./inside", "safe//inside", "safe/", "safe/./inside", "C:/outside",
            "C:outside", "safe\\outside", "safe\x00inside", None,
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_artifact_key(key)

    def test_relative_keys_round_trip_without_the_storage_root(self):
        key = "release-1-example/product-unit-2-007/submission-identifier.d"
        target = self.root / key
        target.mkdir(parents=True)
        self.assertEqual(artifact_key_for_directory(target, self.root), key)
        self.assertEqual(artifact_directory(self.root, key), target)

    def test_missing_directories_are_allowed_only_during_publication_planning(self):
        with self.assertRaises(ValueError):
            artifact_directory(self.root, "missing/receipt")
        self.assertEqual(
            artifact_directory(self.root, "missing/receipt", require_exists=False),
            self.root / "missing/receipt",
        )

    def test_links_are_rejected_including_links_back_inside_storage(self):
        target = self.root / "actual"
        target.mkdir()
        (target / "receipt").mkdir()
        (self.root / "link").symlink_to(target, target_is_directory=True)
        for key in ("link", "link/receipt", "link/missing"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                artifact_directory(self.root, key, require_exists=False)
        with self.assertRaises(ValueError):
            artifact_directory(self.root / "link", "receipt")
        with self.assertRaises(ValueError):
            artifact_key_for_directory(self.root / "link/receipt", self.root)

    def test_outside_directories_cannot_become_receipt_keys(self):
        with self.assertRaises(ValueError):
            artifact_key_for_directory(self.root.parent, self.root)
