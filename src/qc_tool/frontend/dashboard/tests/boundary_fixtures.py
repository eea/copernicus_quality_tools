"""Isolated boundary-generation fixtures for frontend execution prerequisites."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from qc_tool.common import CONFIG


def ready_boundary_package(test_case):
    """Provide the shared resolver's layout, without pretending to contain GIS data."""
    root = Path(test_case.enterContext(TemporaryDirectory()))
    for name in ("raster", "vector"):
        (root / name).mkdir()
    test_case.enterContext(patch.dict(CONFIG, boundary_dir=root))
    return root
