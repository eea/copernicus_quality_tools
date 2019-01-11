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
    if len(shp_filepaths) > 1:
        status.aborted()
        status.add_message("More than one shapefile have been found in the delivery: {:s}."
                           .format(", ".join([shp_filepath.name for shp_filepath in shp_filepaths])))
        return
    shp_filepath = shp_filepaths[0]

    # Check filename and areacode.
    mobj = re.compile(params["filename_regex"], re.IGNORECASE).search(shp_filepath.name)
    if mobj is None:
        status.aborted()
        status.add_message("Shapefile name {:s} is not in accord with specification."
                           .format(shp_filepath.name))
        return
    if mobj.group("areacode") not in params["areacodes"]:
        status.aborted()
        status.add_message("The areacode {:s} extracted from the name of the shapefile"
                           " is not in the list of allowed areacodes."
                           .format(mobj["areacode"]))
        return

    layer_defs = {"rpz": {"src_filepath": shp_filepath,
                          "src_layer_name": shp_filepath.stem}}

    # Find boundary layer.
    boundary_filepath = params["boundary_dir"].joinpath("vector", "boundary_rpz.shp")
    if not boundary_filepath.is_file():
        status.aborted()
        status.add_message("No boundary has been found at {:s}.".format(str(boundary_filepath)))
        return
    layer_defs["boundary"] = {"src_filepath": boundary_filepath, "src_layer_name": boundary_filepath.stem}

    status.add_params({"layer_defs": layer_defs})
