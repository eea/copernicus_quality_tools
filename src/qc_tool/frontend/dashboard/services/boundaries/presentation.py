"""Boundary package presentation values for workspace pages."""

import os
from datetime import datetime
from qc_tool.common import CONFIG
from qc_tool.frontend.dashboard.services.boundaries import BoundaryPackageError
from qc_tool.frontend.dashboard.services.boundaries import resolve_boundary_generation


def get_boundary_version():
    """
    Reads .txt file in boundary/raster folder with format ver_{date}.txt and return datetime string.
    """
    try:
        generation = resolve_boundary_generation(CONFIG["boundary_dir"])
        rasterdir_path = generation.raster_dir
        files_in_rasterpath = os.listdir(rasterdir_path)
        for file_name in files_in_rasterpath:
            if 'ver' in file_name:
                version_str = file_name.split('_')[1].split('.')[0]
                return datetime.strptime(
                    version_str,
                    "%d%m%Y",
                ).strftime("%d/%m/%Y")
    except (BoundaryPackageError, OSError, ValueError, IndexError):
        pass
    return 'Unavailable'
