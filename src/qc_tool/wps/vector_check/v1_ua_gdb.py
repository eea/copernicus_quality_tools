#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from osgeo import ogr

from qc_tool.wps.helper import LayerDefsBuilder
from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    # Fix reference year.
    status.set_status_property("reference_year", params["reference_year"])

    # Find gdb folder.
    gdb_dirs = [path for path in params["unzip_dir"].glob("**") if path.suffix.lower() == ".gdb"]
    if len(gdb_dirs) == 0:
        status.aborted()
        status.add_message("No geodatabase has been found in the delivery.")
        return
    if len(gdb_dirs) > 1:
        status.aborted()
        status.add_message("More than one geodatabase have been found in the delivery: {:s}."
                           .format(", ".join([gdb_dir.name for gdb_dir in gdb_dirs])))
        return
    gdb_dir = gdb_dirs[0]

    # Read all layer infos into builder.
    builder = LayerDefsBuilder(status)
    ds = ogr.Open(str(gdb_dir))
    if ds is None:
        status.aborted()
        status.add_message("Can not open geodatabase {:s}.".format(gdb_dir.name))
        return
    for layer_index in range(ds.GetLayerCount()):
        layer = ds.GetLayerByIndex(layer_index)
        layer_name = layer.GetName()
        builder.add_layer_info(gdb_dir, layer_name)
    ds = None

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
