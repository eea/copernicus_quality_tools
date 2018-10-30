#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import re
from osgeo import ogr

from qc_tool.wps.helper import LayerDefsBuilder
from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    """
    Find layers in a file geodatabase (.gdb) or in a directory with shapefiles.
    """
    # Fix reference year.
    status.set_status_property("reference_year", params["reference_year"])

    # Find gdb folder.
    gdb_dirs = [path for path in params["unzip_dir"].glob("**") if path.suffix.lower() == ".gdb"]
    if len(gdb_dirs) > 1:
        status.aborted()
        status.add_message("More than one geodatabase found in the delivery:"
                           " {:s}.".format(", ".join([gdb_dir.name for gdb_dir in gdb_dirs])))
        return

    builder = LayerDefsBuilder(status)

    if len(gdb_dirs) == 1:
        # We are working with geodatabase.
        gdb_dir = gdb_dirs[0]

        # Read all layer infos into builder.
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

    else:
        # We are working with shapefiles.
        shp_filepaths = [path for path in params["unzip_dir"].glob("**/*") if path.is_file() and path.suffix.lower() == ".shp"]

        # Read all layer infos into builder.
        for filepath in shp_filepaths:
            builder.add_layer_info(filepath, filepath.stem)

    # Check layer count.
    layer_count = len(builder.layer_infos)
    if layer_count not in (2, 5):
        status.aborted()
        status.add_message("There must be exactly 2 or 5 layers, however {:d} found.".format(layer_count))
        return

    # Build layer defs for reference and boundary layers.
    builder.extract_layer_def(params["reference_layer_regex"], "reference")
    builder.extract_layer_def(params["boundary_layer_regex"], "boundary")

    # Build layer defs for revised, combined and change layers.
    if layer_count == 5:
        builder.extract_layer_def(params["revised_layer_regex"], "revised")
        builder.extract_layer_def(params["combined_layer_regex"], "combined")
        builder.extract_layer_def(params["change_layer_regex"], "change")

    status.add_params({"layer_defs": builder.layer_defs})
