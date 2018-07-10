#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Raster resolution check.
"""


from osgeo import gdal

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    """
    Raster resolution check.
    :param params: configuration
    :return: status + message
    """

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

    band_count = ds_open.RasterCount
    if band_count != 1:
        status.add_message("The input raster data contains {:s} bands (1 band is allowed).".format(str(band_count)))
        return

    # get raster pixel size
    gt = ds_open.GetGeoTransform()
    x_size = abs(gt[1])
    y_size = abs(gt[5])

    # verify the square shape of the pixel
    if x_size != y_size:
        status.add_message("The pixel is not square-shaped.")
        return

    # 
    if x_size == params["pixelsize"]:
        return
    else:
        status.add_message("The raster pixel size is {:s} m, {:s} m is allowed.".format(str(x_size), str(params["pixelsize"])))
        return
