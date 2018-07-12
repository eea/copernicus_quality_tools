#! /usr/bin/env python
# -*- coding: utf-8 -*-


import re

from qc_tool.wps.helper import check_name
from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    # Find the shp file.
    shp_filepaths = [path for path in params["unzip_dir"].iterdir() if path.suffix.lower() == ".shp"]
    if len(shp_filepaths) != 1 or not shp_filepaths[0].is_file():
        status.aborted()
        status.add_message("There must be exactly one .shp file.")
        return
    filepath = shp_filepaths[0]

    # Check file name.
    areacode_regex = "({:s})".format("|".join(params["areacodes"]))
    file_name_regex = params["file_name_regex"].replace("areacode", areacode_regex)
    conf = check_name(filepath.name, file_name_regex)
    if not conf:
        status.aborted()
        status.add_message("File name does not conform to the naming convention.")
        return

    # Get layers.
    layer_sources = [(filepath.stem, filepath)]
    status.add_params({"layer_sources": layer_sources})
