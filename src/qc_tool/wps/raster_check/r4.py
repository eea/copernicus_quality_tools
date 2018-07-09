#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CRS check.
"""


from osgeo import gdal
from osgeo import osr

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params):
    """
    CRS check.
    :param params: configuration
    :return: status + message
    """

    dataset = gdal.Open(str(params["filepath"]))
    srs = osr.SpatialReference(dataset.GetProjection())
    if srs.IsProjected() == 0:
        return {"status": "failed",
                "messages": ["The file has no projected coordinate system associated."]}
    epsg = srs.GetAttrValue("AUTHORITY", 1)
    if epsg is None:
        return {"status": "failed",
                "messages": ["The file has EPSG authority missing."]}
    try:
        epsg = int(epsg)
    except:
        return {"status": "failed",
                "messages": ["The EPSG code {:s} is not an integer number.".format(str(epsg))]}
    if epsg not in params["epsg"]:
        return {"status": "failed",
                "messages": ["EPSG code {:s} is not in applicable codes {:s}.".format(str(epsg), str(params["epsg"]))]}
    return {"status": "ok"}
