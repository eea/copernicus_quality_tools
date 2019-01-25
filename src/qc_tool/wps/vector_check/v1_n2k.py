#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import re

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    # Find the shp file.
    shp_filepaths = [path for path in params["unzip_dir"].glob("**/*") if path.is_file() and path.suffix.lower() == ".shp"]
    if len(shp_filepaths) == 0:
        status.aborted()
        status.add_message("No shapefile has been found in the delivery.")
        return
    if len(shp_filepaths) > 1:
        status.aborted()
        status.add_message("More than one shapefile have been found in the delivery: {:s}."
                           .format(", ".join(path.name for path in shp_filepaths)))
        return
    shp_filepath = shp_filepaths[0]

    # Check layer name.
    mobj = re.compile(params["n2k_layer_regex"], re.IGNORECASE).search(shp_filepath.stem)
    if mobj is None:
        status.aborted()
        status.add_message("The layer name {:s} is not in accord with specification.".format(shp_filepath.stem))
        return

    # Get layers.
    layer_defs = {"n2k": {"src_filepath": shp_filepath,
                          "src_layer_name": shp_filepath.stem}}

    # Find boundary layer.
    boundary_filepath = params["boundary_dir"].joinpath("vector", "boundary_n2k.shp")
    if boundary_filepath.is_file():
        layer_defs["boundary"] = {"src_filepath": boundary_filepath, "src_layer_name": boundary_filepath.stem}
    else:
        status.add_message("No boundary has been found at {:s}.".format(str(boundary_filepath)),
                           failed=False)

    status.add_params({"layer_defs": layer_defs})
