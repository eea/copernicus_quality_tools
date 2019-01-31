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
            status.failed("The file can not be opened.")
            return
    except:
        status.failed("The file can not be opened.")
        return

    band_count = ds_open.RasterCount
    if band_count != 1:
        status.failed("The input raster data contains {:s} bands (1 band is allowed).".format(str(band_count)))
        return

    # get raster pixel size
    gt = ds_open.GetGeoTransform()
    x_size = abs(gt[1])
    y_size = abs(gt[5])

    # verify the square shape of the pixel
    if x_size != y_size:
        status.failed("The pixel is not square-shaped.")
        return

    if x_size != params["pixelsize"]:
        status.failed("The raster pixel size is {:s} m, {:s} m is allowed.".format(str(x_size), str(params["pixelsize"])))
