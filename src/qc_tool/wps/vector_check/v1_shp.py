#! /usr/bin/env python
# -*- coding: utf-8 -*-


import re

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    # Find the shp file.
    shp_filepaths = [path for path in params["unzip_dir"].iterdir() if path.suffix.lower() == ".shp"]
    if len(gdb_filepaths) != 1 or not gdb_filepaths[0].is_file():
        status.aborted()
        status.add_message("There must be at least one .shp file in the zip file.")
        return
    filepath = shp_filepaths[0]

    # Get layers.
    layer_sources = [(filepath.stem, filepath)]
    status.add_params({"layer_sources": layer_sources})
