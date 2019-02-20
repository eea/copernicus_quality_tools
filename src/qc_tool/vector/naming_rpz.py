#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import re


DESCRIPTION = "Naming is in accord with specification, Riparian Zones."
IS_SYSTEM = False


def run_check(params, status):
    # Find all shapefiles.
    shp_filepaths = [path for path in params["unzip_dir"].glob("**/*")
                     if path.is_file() and path.suffix.lower() == ".shp"]
    if len(shp_filepaths) == 0:
        status.aborted("No shapefile has been found in the delivery.")
        return
    if len(shp_filepaths) > 1:
        status.aborted("More than one shapefile have been found in the delivery: {:s}."
                       .format(", ".join([shp_filepath.name for shp_filepath in shp_filepaths])))
        return
    shp_filepath = shp_filepaths[0]

    # Check filename and areacode.
    mobj = re.compile(params["filename_regex"], re.IGNORECASE).search(shp_filepath.name)
    if mobj is None:
        status.aborted("Shapefile name {:s} is not in accord with specification."
                       .format(shp_filepath.name))
        return
    if mobj.group("areacode") not in params["areacodes"]:
        status.aborted("The areacode {:s} extracted from the name of the shapefile"
                       " is not in the list of allowed areacodes."
                       .format(mobj["areacode"]))
        return

    layer_defs = {"rpz": {"src_filepath": shp_filepath,
                          "src_layer_name": shp_filepath.stem}}

    # Find boundary layer.
    boundary_filepath = params["boundary_dir"].joinpath("vector", "boundary_rpz.shp")
    if boundary_filepath.is_file():
        layer_defs["boundary"] = {"src_filepath": boundary_filepath, "src_layer_name": boundary_filepath.stem}
    else:
        status.info("No boundary has been found at {:s}.".format(str(boundary_filepath)))

    status.add_params({"layer_defs": layer_defs})
