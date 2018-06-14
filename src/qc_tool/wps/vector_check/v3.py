#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Attribute table structure check.
"""

from osgeo import ogr

from qc_tool.wps.registry import register_check_function
from qc_tool.wps.vector_check.dump_gdbtable import get_fc_path
from qc_tool.wps.helper import find_name, check_name, get_substring


@register_check_function(__name__, "Attribute table contains specified attributes.")
def run_check(filepath, params):
    """
    Attribute table structure check.
    :param filepath: pathname to data source
    :param params: configuration
    :return: status + message
    """
    # get list of field names of particular layers
    ds = ogr.Open(filepath)
    fnames = dict()
    for ln in params["layer_name"]:
        fnames[ln] = list()
        lyr = ds.GetLayerByName(str(ln))
        lyr_defn = lyr.GetLayerDefn()
        for n in range(lyr_defn.GetFieldCount()):
            fdefn = lyr_defn.GetFieldDefn(n)
            fnames[ln].append(str(fdefn.name.lower()))

    # get list of missing field names
    missing_fnames= dict()
    for ln in fnames:
        missing_fnames[ln] = list()
        year = get_substring(ln, "[0-9]{2}")
        for an in params["fields"]:
            if year and "yy" in an:
                an = an.replace("yy", year)
            if not find_name(fnames[ln], an.lower()):
                missing_fnames[ln].append(an.lower().lstrip("^").rstrip("$"))
        if not missing_fnames[ln]:
            del missing_fnames[ln]

    if not missing_fnames:
        return {"status": "ok"}
    else:
        layer_results = ', '.join(
            "layer {!s}: ('{!s}')".format(key, "', '".join(val)) for (key, val) in missing_fnames.items())
        res_message = "Some of the required attributes are missing: ({:s})".format(layer_results)
        return {"status": "failed",
                "message": res_message}
