"""Workers resolve boundary generations without importing frontend adapters."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from qc_tool.boundaries import BoundaryPackageConfigurationError, resolve_boundary_generation


class SharedBoundaryTests(unittest.TestCase):
    def test_resolver_import_is_independent_of_django_and_frontend(self):
        result = subprocess.run(
            [sys.executable, "-c", "import sys; from qc_tool.boundaries import resolve_boundary_generation; "
             "assert not any(k == 'django' or k.startswith('qc_tool.frontend') for k in sys.modules)"],
            capture_output=True, text=True, env=os.environ.copy(), check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_managed_reader_pins_generation_and_refuses_unsafe_pointer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            generation = "gen-" + "a" * 32
            target = root / ".boundary-generations" / generation
            for directory in ("raster", "vector"):
                (target / directory).mkdir(parents=True)
            pointer = root / ".boundary-current"
            pointer.symlink_to(".boundary-generations/" + generation)
            snapshot = resolve_boundary_generation(root)
            self.assertEqual(snapshot.path, target)
            self.assertTrue(snapshot.managed)
            pointer.unlink()
            pointer.symlink_to("/outside")
            self.assertEqual(snapshot.raster_dir, target / "raster")
            with self.assertRaises(BoundaryPackageConfigurationError):
                resolve_boundary_generation(root)


if __name__ == "__main__":
    unittest.main()
