#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from osgeo import gdal
from osgeo import osr

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    dataset = gdal.Open(str(params["filepath"]))
    srs = osr.SpatialReference(dataset.GetProjection())
    if srs.IsProjected() == 0:
        status.add_message("The file has no projected coordinate system associated.")
        return
    epsg = srs.GetAttrValue("AUTHORITY", 1)
    if epsg is None:
        status.add_message("The file has EPSG authority missing.")
        return
    try:
        epsg = int(epsg)
    except:
        status.add_message("The EPSG code {:s} is not an integer number.".format(str(epsg)))
        return
    if epsg not in params["epsg"]:
        status.add_message("EPSG code {:s} is not in applicable codes {:s}.".format(str(epsg), str(params["epsg"])))
        return
    return
