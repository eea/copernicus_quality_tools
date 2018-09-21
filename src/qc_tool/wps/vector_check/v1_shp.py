#! /usr/bin/env python3
# -*- coding: utf-8 -*-

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    # Find the shp file.
    all_filepaths = [path for path in params["unzip_dir"].glob("**/*")]
    shp_filepaths = [path for path in all_filepaths if path.suffix.lower() == ".shp"]

    if len(shp_filepaths) != 1 or not shp_filepaths[0].is_file():
        status.aborted()
        status.add_message("There must be at least one .shp file in the zip file.")
        return
    filepath = shp_filepaths[0]

    # Get layers.
    layer_sources = [(filepath.stem.lower(), filepath)]
    status.add_params({"layer_sources": layer_sources})
