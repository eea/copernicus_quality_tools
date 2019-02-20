#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import re

from osgeo import ogr


DESCRIPTION = "Attribute table is composed of prescribed attributes."
IS_SYSTEM = False


def run_check(params, status):
    # check for .vat.dbf file existence
    dbf_filename = "{:s}.vat.dbf".format(params["filepath"].name)
    dbf_filepath = params["filepath"].with_name(dbf_filename)

    if not dbf_filepath.is_file():
        status.failed("Attribute table file (.vat.dbf) is missing.")
        return

    ds = ogr.Open(str(dbf_filepath))
    layer = ds.GetLayer()
    attr_names = [field_defn.name for field_defn in layer.schema]
    missing_attr_regexes = []
    for attr_regex in params["attribute_regexes"]:
        is_missing = True
        for attr_name in attr_names:
            mobj = re.match("{:s}$".format(attr_regex), attr_name, re.IGNORECASE)
            if mobj is not None:
                is_missing = False
                break
        if is_missing:
            missing_attr_regexes.append(attr_regex)
    if len(missing_attr_regexes) > 0:
        missing_attr_message = ", ".join(missing_attr_regexes)
        status.failed("Raster attribute table has missing attributes: {:s}.".format(missing_attr_message))
