#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Attribute table structure check.
"""

from pathlib import Path
import ogr

from qc_tool.wps.registry import register_check_function
from qc_tool.wps.helper import find_name

@register_check_function(__name__, "Attribute table contains specified attributes.")
def run_check(filepath, params):
    """
    Attribute table structure check.
    :param filepath: pathname to data source
    :param params: configuration
    :return: status + message
    """

    # check for .dbf file existence
    dbf_filepath = filepath + ".vat.dbf"
    if not Path(dbf_filepath).is_file():
        return {"status": "failed",
                "message": "Attribute table file (.vat.dbf) is missing."}

    # get list of field names
    ds = ogr.Open(dbf_filepath)
    lyr = ds.GetLayer()
    fnames = list()
    lyr_defn = lyr.GetLayerDefn()
    for n in range(lyr_defn.GetFieldCount()):
        fdefn = lyr_defn.GetFieldDefn(n)
        fnames.append(fdefn.name.lower())

    # check for required field names existence
    missing_fnames= list()
    for an in params["fields"]:
        if not find_name(fnames, an.lower()):
            missing_fnames.append(an.lower().lstrip("^").rstrip("$"))
    if not missing_fnames:
        return {"status": "ok"}
    else:
        missing_fnames_str = "', '".join(missing_fnames)
        return {"status": "failed",
                "message": "Some of the required attributes are missing: '{:s}'.".format(missing_fnames_str)}