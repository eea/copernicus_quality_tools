#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import re

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    # Find all shapefiles.
    shp_filepaths = [path for path in params["unzip_dir"].glob("**/*")
                     if path.is_file() and path.suffix.lower() == ".shp"]
    if len(shp_filepaths) == 0:
        status.aborted()
        status.add_message("No shapefile has been found in the delivery.")
        return

    # Filter out shp filepaths by areacodes.
    areacodes_subregex = "({:s})".format("|".join(params["areacodes"]))
    filename_regex = re.compile(params["filename_regex"].format(areacodes=areacodes_subregex), re.IGNORECASE)
    matched_shp_filepaths = [shp_filepath for shp_filepath in shp_filepaths if filename_regex.search(shp_filepath.name)]
    if len(matched_shp_filepaths) == 0:
        status.aborted()
        status.add_message("No shapefile with a name following product specification has been found.")
        return
    if len(matched_shp_filepaths) > 1:
        status.aborted()
        status.add_message("More than one shapefile with a name following product specification have been found: {:s}."
                           .format(", ".join(path.name for path in matched_shp_filepaths)))
        return

    layer_defs = {"rpz": {"src_filepath": matched_shp_filepaths[0],
                          "src_layer_name": matched_shp_filepaths[0].stem}}
    status.add_params({"layer_defs": layer_defs})
