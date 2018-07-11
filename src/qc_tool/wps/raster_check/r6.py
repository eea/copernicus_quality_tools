#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from osgeo import gdal

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    # enable gdal to use exceptions
    gdal.UseExceptions()

    try:
        ds_open = gdal.Open(str(params["filepath"]))
        if ds_open is None:
            status.add_message("The file can not be opened.")
            return
    except:
        status.add_message("The file can not be opened.")
        return

    # upper-left coordinate divided by pixel-size must leave no remainder
    gt = ds_open.GetGeoTransform()
    ulx = gt[0]
    uly = gt[3]
    pixelsizex = gt[1]
    pixelsizey = gt[5]

    if ulx % pixelsizex != 0 or uly % pixelsizey != 0:
        return {"status": "failed",
                "messages": ["The upper-left X, Y coordinates are not divisible by pixel-size with no remainder."]}

    # Pan-European layers must fit to the LEAC 1 km grid
    filename = params["filepath"].name
    if "_eu_" in filename:
        if ulx % 1000 != 0 or uly % 1000 != 0:
            status.add_mesage("The raster origin does not fit to the LEAC 1 km grid.")
            return

    return
