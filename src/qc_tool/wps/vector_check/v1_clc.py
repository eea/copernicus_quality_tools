#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import re

from qc_tool.wps.registry import register_check_function
from qc_tool.wps.vector_check.dump_gdbtable import get_fc_path


@register_check_function(__name__)
def run_check(params, status):
    # Find gdb directory.
    gdb_dirs = [path for path in params["unzip_dir"].iterdir() if path.is_dir() and path.suffix.lower() == ".gdb"]
    if len(gdb_dirs) != 1:
        status.aborted()
        status.add_message("There must be exactly one .gdb directory.")
        return
    gdb_dir = gdb_dirs[0]

    # Check file name.
    mobj = re.compile(params["filename_regex"], re.IGNORECASE).search(gdb_dir.name)
    if mobj is None:
        status.aborted()
        status.add_message("Filename does not conform to the naming convention.")
        return

    # Get country code.
    countrycode = mobj.group("country_code")
    if countrycode.lower() not in params["country_codes"]:
        status.aborted()
        status.add_message("Filename has illegal country code {:s}.".format(country_code))
        return

    # Get reference year.
    reference_year = mobj.group("reference_year")
    status.set_status_property("reference_year", reference_year)

    # Get list of feature classes matching the layer prefix and layer name.
    layer_names = get_fc_path(str(gdb_dir))
    layer_prefix_regex = re.compile(params["layer_prefix_regex"].format(countrycode=countrycode), re.IGNORECASE)
    layer_names_by_prefix = [layer_name for layer_name in layer_names if layer_prefix_regex.search(layer_name) is not None]
    layer_name_regex = re.compile(params["layer_name_regex"].format(countrycode=countrycode), re.IGNORECASE)
    layer_names_by_name = [layer_name for layer_name in layer_names if layer_prefix_regex.search(layer_name) is not None]

    if set(layer_names_by_prefix) - set(layer_names_by_name):
        status.aborted()
        status.add_message("Number of layers matching prefix '{:s}'"
                           " and number of layers matching name '{:s}'"
                           " are not equal.".format(params["layer_prefix_regex"], params["layer_name_regex"]))
    elif len(layer_names_by_name) != int(params["layer_count"]):
        status.aborted()
        status.add_message("Number of matching layers ({:d}) does not correspond with"
                           " declared number of layers({:d})".format(len(layer_names_by_name),
                                                                     int(params["layer_count"])))
    else:
        # Strip country code feature dataset from layer name.
        layer_names = [layer_name.split("/")[-1] for layer_name in layer_names_by_name]

        layer_aliases = {"layer_{:d}".format(i): {"src_filepath": gdb_dir,
                                                  "src_layer_name": layer_name}
                         for i, layer_name in enumerate(layer_names)}
        status.add_params({"layer_aliases": layer_aliases})
        if params.get("is_border_source", False):
            status.add_params({"border_source_layer": layer_names[0]})
