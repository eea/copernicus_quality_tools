#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from osgeo import gdal

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    ds = gdal.Open(str(params["filepath"]))

    if ds is None:
        status.aborted("The raster {:s} could not be opened.".format(params["filepath"].name))
        return

    # get the number of bands
    num_bands = ds.RasterCount
    if num_bands != 1:
        status.failed("The raster has {:d} bands. The expected number of bands is one.".format(num_bands))
        return

    # get the DataType of the band ("Byte" means 8-bit depth)
    band = ds.GetRasterBand(1)

    # check the color table of the band
    ct = band.GetRasterColorTable()
    if ct is None:
        status.failed("The raster {:s} has color table missing.".format(params["filepath"].name))
