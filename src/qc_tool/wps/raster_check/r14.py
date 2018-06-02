#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Color table existence check
"""

from osgeo import gdal

from qc_tool.wps.registry import register_check_function

@register_check_function(__name__, "Raster has a color table")
def run_check(filepath, params):
    """
    :return: status + message
    """
    ds = gdal.Open(filepath)

    if ds is None:
        return {"status": "aborted",
                "message": "The raster {:s} could not be opened.".format(filepath)}

    # get the number of bands
    num_bands = ds.RasterCount
    if num_bands != 1:
        return {"status": "failed",
                "message": "The raster has {:d} bands. \
                            expected number of bands is one.".format(num_bands)}

    # get the DataType of the band ("Byte" means 8-bit depth)
    band = ds.GetRasterBand(1)

    # check the color table of the band
    ct = band.GetRasterColorTable()
    if ct is None:
        return {"status": "failed",
                "message": "The raster {:s} does not have a \
                            color table.".format(filepath)}
    else:
        return {"status": "ok"}
