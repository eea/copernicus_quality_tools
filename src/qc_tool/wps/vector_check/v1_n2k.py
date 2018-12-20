#! /usr/bin/env python3
# -*- coding: utf-8 -*-


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

    # Get layers.
    layer_defs = {"n2k": {"src_filepath": shp_filepaths[0],
                          "src_layer_name": shp_filepaths[0].stem}}
    status.add_params({"layer_defs": layer_defs})
