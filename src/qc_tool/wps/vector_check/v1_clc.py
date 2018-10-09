#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import re

from qc_tool.wps.registry import register_check_function
from qc_tool.wps.vector_check.dump_gdbtable import get_fc_path

def check_name(name, template):
    regex = re.compile(template)
    return bool(regex.match(name))


@register_check_function(__name__)
def run_check(params, status):
    # Find gdb directory.
    gdb_filepaths = [path for path in params["unzip_dir"].iterdir() if path.suffix.lower() == ".gdb"]
    if len(gdb_filepaths) != 1 or not gdb_filepaths[0].is_dir():
        status.aborted()
        status.add_message("There must be exactly one .gdb directory.")
        return
    filepath = gdb_filepaths[0]

    # check file name
    filename = filepath.name.lower()
    mobj = re.match(params["file_name_regex"], filename)
    if mobj is None:
        status.aborted()
        status.add_message("File name does not conform to the naming convention.")
        return

    # Get country code.
    countrycode = mobj.group("country_code")
    if countrycode not in params["country_codes"]:
        status.aborted()
        status.add_message("File name has illegal country code {:s}.".format(country_code))
        return

    # Get reference year.
    reference_year = mobj.group("reference_year")
    status.set_status_property("reference_year", reference_year)

    # get list of feature classes
    layer_names = get_fc_path(str(filepath))
    layer_names = [layer_name.lower() for layer_name in layer_names]

    # get list of feature classes matching to the prefix and regex
    layer_prefix = params["layer_prefix"].format(countrycode=countrycode)
    layer_regex = params["layer_regex"].format(countrycode=countrycode).lower()
    layer_names_by_prefix = [layer_name for layer_name in layer_names
                             if check_name(layer_name, layer_prefix)]
    layer_names_by_regex = [layer_name for layer_name in layer_names
                            if check_name(layer_name, layer_regex)]

    if set(layer_names_by_prefix) - set(layer_names_by_regex):
        status.aborted()
        status.add_message("Number of layers matching prefix '{:s}'"
                           " and number of layers matching regex '{:s}'"
                           " are not equal.".format(layer_prefix, layer_regex))
    elif len(layer_names_by_regex) != int(params["layer_count"]):
        status.aborted()
        status.add_message("Number of matching layers ({:d}) does not correspond with"
                           " declared number of layers({:d})".format(len(layer_names_by_regex),
                                                                     int(params["layer_count"])))
    else:
        # Strip country code feature dataset from layer name.
        layer_names = [layer_name.split("/")[-1] for layer_name in layer_names_by_regex]

        layer_aliases = {"layer_{:d}".format(i): {"src_filepath": filepath,
                                                  "src_layer_name": layer_name}
                         for i, layer_name in enumerate(layer_names)}
        status.add_params({"layer_aliases": layer_aliases})
        if params.get("is_border_source", False):
            status.add_params({"border_source_layer": layer_names[0]})
