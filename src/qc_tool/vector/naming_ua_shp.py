#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Naming is in accord with specification, Urban Atlas shapefiles."
IS_SYSTEM = False


def run_check(params, status):
    from qc_tool.vector.helper import LayerDefsBuilder

    # Fix reference year.
    status.set_status_property("reference_year", params["reference_year"])

    # Find all shapefiles.
    shp_filepaths = [path for path in params["unzip_dir"].glob("**/*")
                     if path.is_file() and path.suffix.lower() == ".shp"]
    if len(shp_filepaths) == 0:
        status.aborted("No shapefile has been found in the delivery.")
        return

    # Read all layer infos into builder.
    builder = LayerDefsBuilder(status)
    for filepath in shp_filepaths:
        builder.add_layer_info(filepath, filepath.stem)

    # Build layer defs for reference and boundary layers.
    builder.extract_layer_def(params["reference_layer_regex"], "reference")
    builder.extract_layer_def(params["boundary_layer_regex"], "boundary")

    # Build layer defs for revised, combined and change layers.
    if "revised_layer_regex" in params:
        builder.extract_layer_def(params["revised_layer_regex"], "revised")
        builder.extract_layer_def(params["combined_layer_regex"], "combined")
        builder.extract_layer_def(params["change_layer_regex"], "change")

    builder.check_excessive_layers()

    status.add_params({"layer_defs": builder.layer_defs})