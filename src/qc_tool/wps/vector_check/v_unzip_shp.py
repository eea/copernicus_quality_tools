#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import re
from zipfile import ZipFile

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    zip_filepath = params["filepath"]
    extract_dir = params["tmp_dir"].joinpath("v_unzip_shp.d")
    extract_dir.mkdir()

    # Unzip the source zip file.
    try:
        with ZipFile(str(zip_filepath)) as zip_file:
            zip_file.extractall(path=str(extract_dir))
    except Exception as ex:
        status.aborted()
        status.add_message("Error unzipping file {:s}.".format(zip_filepath.name))
        return

    # Find the shp files.
    shp_filepaths = [path for path in list(extract_dir.glob("**/*")) if path.suffix.lower() ==".shp" and path.is_file()]
    if len(shp_filepaths) == 0:
        status.aborted()
        status.add_message("There must be at least one .shp file in the zip file.")
        return

    # Find the parent directory of the shp file. All shp files in the zip should have the same parent directory.
    shp_dirs = []

    # Find the primary shp file. This is the file matching the file name regex.
    for shp_filepath in shp_filepaths:
        shp_dir = shp_filepath.parents[0]
        if not shp_dir in shp_dirs:
            shp_dirs.append(shp_dir)

    if len(shp_dirs) != 1:
        status.aborted()
        status.add_message("All .shp file(s) must be inside the same directory in the zip file.")

    status.add_params({"filepath": shp_dirs[0]})
