#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import re

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    # Find all .shp files in the tree
    all_filepaths = [path for path in params["unzip_dir"].glob("**/*") if path.is_file()]
    shp_filepaths = [path for path in all_filepaths if path.suffix.lower() == ".shp"]

    if len(shp_filepaths) == 0:
        status.aborted()
        status.add_message("There must be a .shp file in the delivery.")
        return

    # replace AREACODE placeholder in the naming pattern with valid area codes.
    areacode_regex = "({:s})".format("|".join(params["areacodes"]))
    pattern = params["file_name_regex"].replace("AREACODE", areacode_regex)
    file_name_regex = re.compile(pattern, re.IGNORECASE)

    matched_filepaths = [path for path in shp_filepaths if file_name_regex.match(path.name)]
    if len(matched_filepaths) != 1:
        status.aborted()
        status.add_message("There must be exactly one .shp file which conforms to prescribed naming convention.")
        return

    # Get layers. Layer names are always considered lower-case.
    layer_aliases = {"rpz_layer": {"src_filepath": matched_filepaths[0],
                                   "src_layer_name": matched_filepaths[0].stem.lower()}}
    status.add_params({"layer_aliases": layer_aliases})
