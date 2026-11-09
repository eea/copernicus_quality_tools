"""Worker-reported artifact roles stay inside the prepared evidence mount."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts.testing.artifacts import retained_worker_paths


class WorkerArtifactPathsTests(TestCase):
    def roles(self):
        return {"directory": "job", "result": "job/result.json",
                "specification": "job/specification/EXAMPLE.json", "outputs": "job/outputs"}

    def test_relative_roles_preserve_the_configured_evidence_root(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("scripts.testing.artifacts.subprocess.check_output", return_value=json.dumps(self.roles())):
                paths = retained_worker_paths("isolated-worker", "uuid", root, "example", "EXAMPLE.json")
            self.assertEqual(paths["specification"], root / "job/specification/EXAMPLE.json")
            self.assertEqual(paths["outputs"], root / "job/outputs")

    def test_traversal_absolute_paths_and_symlink_escape_are_refused(self):
        with TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "evidence"
            root.mkdir()
            (root / "escape").symlink_to(parent, target_is_directory=True)
            for key in ("../result.json", "/tmp/result.json", "escape/result.json"):
                roles = {**self.roles(), "result": key}
                with self.subTest(key=key), patch(
                    "scripts.testing.artifacts.subprocess.check_output", return_value=json.dumps(roles),
                ), self.assertRaises(ValueError):
                    retained_worker_paths("isolated-worker", "uuid", root, "example", "EXAMPLE.json")
