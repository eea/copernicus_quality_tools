#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import re

from qc_tool.wps.helper import LayerDefsBuilder
from qc_tool.wps.registry import register_check_function
from qc_tool.wps.vector_check.dump_gdbtable import get_fc_path


@register_check_function(__name__)
def run_check(params, status):
    # Fix reference year.
    status.set_status_property("reference_year", params["reference_year"])

    # Find gdb directory.
    gdb_dirs = [path for path in params["unzip_dir"].glob("**") if path.suffix.lower() == ".gdb"]
    if len(gdb_dirs) == 0:
        status.aborted()
        status.add_message("Can not find geodatabase in the delivery.")
        return
    if len(gdb_dirs) > 1:
        status.aborted()
        status.add_message("More than one geodatabase found in the delivery:"
                           " {:s}.".format(", ".join([gdb_dir.name for gdb_dir in gdb_dirs])))
        return
    gdb_dir = gdb_dirs[0]

    # Check file name.
    mobj = re.compile(params["filename_regex"], re.IGNORECASE).search(gdb_dir.name)
    if mobj is None:
        status.aborted()
        status.add_message("Gdb filename {:s} is not in accord with specification.".format(gdb_dir.name))
        return

    # Extract and check country code.
    country_code = mobj.group("country_code")
    country_code = country_code.lower()
    if country_code not in params["country_codes"]:
        status.aborted()
        status.add_message("Filename has illegal country code {:s}.".format(country_code))
        return

    # Read all layers.
    builder = LayerDefsBuilder(status)
    # NOTE:
    # Normally we would use ogr for reading layer names.
    # However, we are reading the layers using get_fc_path() function.
    # Such function returns the whole name including feature dataset component
    # (the part before "/").
    for layer_name in get_fc_path(str(gdb_dir)):
        builder.add_layer_info(gdb_dir, layer_name)

    # Build layer defs.
    builder.set_tpl_params(country_code=country_code)
    builder.extract_layer_def(params["reference_layer_regex"], "reference")
    builder.extract_layer_def(params["change_layer_regex"], "change")
    builder.extract_layer_def(params["initial_layer_regex"], "initial")

    # Excessive layers should fail.
    builder.check_excessive_layers()

    # Strip feature dataset component from layer_defs.
    layer_defs = builder.layer_defs
    for layer_def in layer_defs.values():
            layer_def["src_layer_name"] = layer_def["src_layer_name"].split("/")[-1]

    # Find boundary layer.
    bdir = params["boundary_dir"].joinpath("vector")
    boundary_filepaths = [path for path in bdir.glob("**/boundary_{:s}.shp".format(country_code)) if path.is_file()]
    if len(boundary_filepaths) == 0:
        status.aborted()
        status.add_message("Can not find boundary for country {:s} under directory {:s}.".format(country_code, str(bdir)))
        return
    if len(boundary_filepaths) > 1:
        status.aborted()
        status.add_message("More than one boundary found for country {:s}: {:s}.".format(country_code, ", ".join(str(p) for p in boundary_filepaths)))
        return
    layer_defs["boundary"] = {"src_filepath": boundary_filepaths[0], "src_layer_name": boundary_filepaths[0].stem}

    status.add_params({"layer_defs": layer_defs})