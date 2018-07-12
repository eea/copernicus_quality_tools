#! /usr/bin/env python
# -*- coding: utf-8 -*-


import re

from qc_tool.wps.helper import check_name
from qc_tool.wps.registry import register_check_function
from qc_tool.wps.vector_check.dump_gdbtable import get_fc_path


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
    file_name_regex = params["file_name_regex"].replace("countrycode", params["country_codes"]).lower()
    conf = check_name(filename, file_name_regex)
    if not conf:
        status.aborted()
        status.add_message("File name does not conform to the naming convention.")
        return

    # get particular country code
    cc_regex = params["file_name_regex"].replace("countrycode", "(.+?)")
    countrycode = re.search(cc_regex, filename).group(1)

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
        return
    elif len(layer_names_by_regex) != int(params["layer_count"]):
        status.aborted()
        status.add_message("Number of matching layers ({:d}) does not correspond with"
                           " declared number of layers({:d})".format(len(layer_names_by_regex),
                                                                     int(params["layer_count"])))
        return
    else:
        # Strip country code feature dataset from layer name.
        layer_names = [layer_name.split("/")[-1] for layer_name in layer_names_by_regex]
        layer_sources = [(layer_name, filepath) for layer_name in layer_names]
        status.add_params({"layer_sources": layer_sources})
        return
