#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CRS check.
"""

import osr
import gdal

from registry import register_check_function

@register_check_function(__name__, "EPSG code of file CRS match reference EPSG code.")
def run_check(filepath, params):
    """
    CRS check.
    :param filepath: pathname to data source
    :param params: configuration
    :return: status + message
    """

    print("run_check.filepath={:s}".format(repr(filepath)))
    print("run_check.params={:s}".format(repr(params)))

    dsopen = gdal.Open(filepath)
    srs = osr.SpatialReference(dsopen.GetProjection())
    if srs.IsProjected:
        epsg = srs.GetAttrValue("AUTHORITY", 1)
    else:
        return {"status": "failed",
                "message": "the data is not projected"}

    # CRS check via EPSG comparison
    if epsg in map(str, params["epsg"]):
        return {"status": "ok",
                "message": "the CRS check was successful"}
    else:
        return {"status": "failed",
                "message": "forbidden EPSG code: {:s}".format(epsg)}
