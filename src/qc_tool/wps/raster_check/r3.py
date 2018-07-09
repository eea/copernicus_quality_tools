#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Attribute table structure check.
"""


from osgeo import ogr

from qc_tool.wps.helper import find_name
from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params):
    """
    Attribute table structure check.
    :param params: configuration
    :return: status + message
    """

    # check for .vat.dbf file existence
    dbf_filename = "{:s}.vat.dbf".format(params["filepath"].name)
    dbf_filepath = params["filepath"].with_name(dbf_filename)
    if not dbf_filepath.is_file():
        return {"status": "failed",
                "messages": ["Attribute table file (.vat.dbf) is missing."]}

    # get list of field names
    ds = ogr.Open(str(dbf_filepath))
    lyr = ds.GetLayer()
    fnames = list()
    lyr_defn = lyr.GetLayerDefn()
    for n in range(lyr_defn.GetFieldCount()):
        fdefn = lyr_defn.GetFieldDefn(n)
        fnames.append(fdefn.name.lower())

    # check for required field names existence
    missing_fnames = list()
    for an in params["fields"]:
        if not find_name(fnames, an.lower()):
            missing_fnames.append(an.lower().lstrip("^").rstrip("$"))
    if not missing_fnames:
        return {"status": "ok"}
    else:
        missing_fnames_str = "', '".join(missing_fnames)
        return {"status": "failed",
                "messages": ["Some of the required attributes are missing: '{:s}'.".format(missing_fnames_str)]}
