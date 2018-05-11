#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CRS check.
"""

import osr
import gdal

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__, "EPSG code of file CRS match reference EPSG code.")
def run_check(filepath, params):
    """
    CRS check.
    :param filepath: pathname to data source
    :param params: configuration
    :return: status + message
    """

    dataset = gdal.Open(filepath)
    srs = osr.SpatialReference(dataset.GetProjection())
    if srs.IsProjected() == 0:
        return {"status": "failed",
                "message": "The file has no projected coordinate system associated."}
    epsg = srs.GetAttrValue("AUTHORITY", 1)
    if epsg is None:
        return {"status": "failed",
                "message": "The file has EPSG authority missing."}
    try:
        epsg = int(epsg)
    except:
        return {"status": "failed",
                "message": "The EPSG code {:s} is not an integer number.".format(str(epsg))}
    if epsg not in params["epsg"]:
        return {"status": "failed",
                "message": "EPSG code {:s} is not in applicable codes {:s}.".format(str(epsg), str(params["epsg"]))}

    return {"status": "ok",
            "message": "the CRS check was successful"}
