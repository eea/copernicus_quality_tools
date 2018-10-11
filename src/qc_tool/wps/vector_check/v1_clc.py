#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import re

from qc_tool.wps.registry import register_check_function
from qc_tool.wps.vector_check.dump_gdbtable import get_fc_path


@register_check_function(__name__)
def run_check(params, status):
    # Find gdb directory.
    gdb_dirs = [path for path in params["unzip_dir"].glob("**") if path.suffix.lower() == ".gdb"]
    if len(gdb_dirs) != 1:
        status.aborted()
        status.add_message("There must be exactly one .gdb directory in the delivery.")
        return
    gdb_dir = gdb_dirs[0]

    # Check file name.
    mobj = re.compile(params["filename_regex"], re.IGNORECASE).search(gdb_dir.name)
    if mobj is None:
        status.aborted()
        status.add_message("Gdb filename {:s} is not in accord with specification.".format(gdb_dir.name))
        return

    # Extract and check reference year.
    #
    # Reference year must not fall in the first campaign.
    # The first campaign is there in order to be able to get the year of initial layer.
    reference_year = mobj.group("reference_year")
    if reference_year not in params["campaign_years"][1:]:
        status.aborted()
        status.add_message("Reference year {:s} does not fall in"
                           " campaign years {!r:s}.".format(reference_year, params["campaign_years"][1:]))
        return
    status.set_status_property("reference_year", reference_year)

    # Extract and check country code.
    country_code = mobj.group("country_code")
    if country_code.lower() not in params["country_codes"]:
        status.aborted()
        status.add_message("Filename has illegal country code {:s}.".format(country_code))
        return

    # Build layer defs.
    builder = LayerDefsBuilder(gdb_dir, status)
    builder.add_tpl_param("country_code", country_code)
    builder.add_tpl_param("reference_year_tail", reference_year[-2:])
    initial_year = params["campaign_years"][params["campaign_years"].index(reference_year) - 1]
    builder.add_tpl_param("initial_year_tail", initial_year[-2:])
    builder.add_layer_def(params["reference_layer_regex"], "reference")
    builder.add_layer_def(params["change_layer_regex"], "change")
    builder.add_layer_def(params["initial_layer_regex"], "initial")

    # Excessive layers should fail.
    if len(builder.layer_names) > 0:
        status.add_message("There are excessive layers: {:s}.".format(", ".join(builder.layer_names)))

    status.add_params({"layer_defs": builder.layer_defs})


class LayerDefsBuilder():
    def __init__(self, gdb_dir, status):
        self.gdb_dir = gdb_dir
        self.status = status
        self.tpl_params = {}
        self.layer_defs = {}
        self.layer_names = get_fc_path(str(gdb_dir))

    def add_tpl_param(self, tpl_key, tpl_value):
        self.tpl_params[tpl_key] = tpl_value

    def add_layer_def(self, regex, layer_alias):
        regex = regex.format(**self.tpl_params)
        regex = re.compile(regex, re.IGNORECASE)
        matches = [name for name in self.layer_names if regex.search(name)]
        if len(matches) == 0:
            self.status.aborted()
            self.status.add_message("Can not find {:s} layer.".format(layer_alias))
            return
        if len(matches) > 1:
            self.status.aborted()
            self.status.add_message("Found {:d} {:s} layers.".format(len(matches), layer_alias))
            return

        # Pop the layer name from the list.
        layer_name = self.layer_names.pop(self.layer_names.index(matches[0]))

        # Strip country code feature dataset from layer name.
        layer_name = layer_name.split("/")[-1]

        # Add layer def.
        self.layer_defs[layer_alias] = {"src_filepath": self.gdb_dir, "src_layer_name": layer_name}
