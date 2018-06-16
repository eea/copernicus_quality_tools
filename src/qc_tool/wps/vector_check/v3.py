#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Attribute table structure check.
"""

from osgeo import ogr

from qc_tool.wps.registry import register_check_function
from qc_tool.wps.helper import find_name, get_substring


@register_check_function(__name__, "Attribute table contains specified attributes.")
def run_check(filepath, params):
    """
    Attribute table structure check.
    :param filepath: pathname to data source
    :param params: configuration
    :return: status + message
    """
    # get list of actual field names of all layers
    ds = ogr.Open(filepath)
    layer_fields = dict()
    for ln in params["layer_names"]:
        layer = ds.GetLayerByName(str(ln))
        layer_fields[ln] = [field.name.lower() for field in layer.schema]

    # The list of missing field names will be stored by layer
    missing = dict()
    for ln in layer_fields:
        missing[ln] = list()
        year = get_substring(ln, "[0-9]{2}")
        for an in params["fields"]:
            if year and "yy" in an:
                an = an.replace("yy", year)
            # check if there are any actual field names that match the template
            matching_fieldnames = list(find_name(layer_fields[ln], an.lower()))
            if not matching_fieldnames:
                missing[ln].append(an.lower().lstrip("^").rstrip("$"))

        if not missing[ln]:
            del missing[ln]

    if not missing:
        return {"status": "ok"}
    else:
        # report missing fields for each layer
        layer_results = ", ".join("layer {!s}: ('{!s}')".format(ln, "', '".join(fn)) for (ln, fn) in missing.items())
        res_message = "Some of the required attributes are missing: ({:s})".format(layer_results)
        return {"status": "failed",
                "message": res_message}
