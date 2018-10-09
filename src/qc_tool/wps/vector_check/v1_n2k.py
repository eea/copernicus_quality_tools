#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    # Find the shp file.
    shp_filepaths = [path for path in params["unzip_dir"].glob("**/*") if path.is_file() and path.suffix.lower() == ".shp"]
    if len(shp_filepaths) != 1:
        status.aborted()
        status.add_message("There must be exactly one .shp file in the zip file.")
        return

    # Get layers.
    layer_aliases = {"n2k_layer": {"src_filepath": shp_filepaths[0],
                                   "src_layer_name": shp_filepaths[0].stem}}
    status.add_params({"layer_aliases": layer_aliases})
