#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Bounding box upper left corner is positioned on grid."
IS_SYSTEM = False


def run_check(params, status):
    import osgeo.gdal as gdal

    ds = gdal.Open(str(params["filepath"]))

    # upper-left coordinate divided by pixel-size must leave no remainder
    gt = ds.GetGeoTransform()
    ulx = gt[0]
    uly = gt[3]
    pixelsizex = gt[1]
    pixelsizey = gt[5]

    if ulx % pixelsizex != 0 or uly % pixelsizey != 0:
        status.failed("The upper-left X, Y coordinates are not divisible by pixel-size with no remainder.")
        return

    # Pan-European layers must fit to the LEAC 1 km grid
    filename = params["filepath"].name
    if "_eu_" in filename:
        if ulx % 1000 != 0 or uly % 1000 != 0:
            status.failed("The raster origin does not fit to the LEAC 1 km grid.")
