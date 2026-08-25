"""Tests for bounded boundary-file presentation metadata."""

from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from qc_tool.frontend.dashboard.services.boundaries import (
    BoundaryCatalogLimitExceeded,
)
from qc_tool.frontend.dashboard.services.boundaries import list_boundary_files


class BoundaryCatalogTests(SimpleTestCase):
    def test_lists_only_supported_files_in_stable_order(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "nested").mkdir()
            (root / "zeta.TIF").write_bytes(b"123")
            (root / "nested" / "alpha.tif").write_bytes(b"1")
            (root / "ignored.txt").write_bytes(b"ignored")

            files = list_boundary_files(root, "raster")

        self.assertEqual(
            [boundary_file.as_dict() for boundary_file in files],
            [
                {"filename": "alpha.tif", "size_bytes": 1, "type": "raster"},
                {"filename": "zeta.TIF", "size_bytes": 3, "type": "raster"},
            ],
        )

    def test_rejects_an_unsupported_boundary_type(self):
        with TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(ValueError, "raster or vector"):
                list_boundary_files(temporary_directory, "unknown")

    def test_stops_when_the_recursive_scan_limit_is_exceeded(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "first.tif").write_bytes(b"1")
            (root / "second.tif").write_bytes(b"2")

            with self.assertRaises(BoundaryCatalogLimitExceeded):
                list_boundary_files(root, "raster", max_entries=1)
