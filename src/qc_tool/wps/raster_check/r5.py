#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Raster resolution check.
"""


from osgeo import gdal

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params):
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
            return {"status": "failed",
                    "message": "The file can not be opened."}
    except:
        return {"status": "failed",
                "message": "The file can not be opened."}

    band_count = ds_open.RasterCount
    if band_count != 1:
        return {"status": "failed",
                "message": "The input raster data contains {:s} bands (1 band is allowed).".format(str(band_count))}

    # get raster pixel size
    gt = ds_open.GetGeoTransform()
    x_size = abs(gt[1])
    y_size = abs(gt[5])

    # verify the square shape of the pixel
    if x_size != y_size:
        return {"status": "failed",
                "message": "The pixel is not square-shaped."}

    # 
    if x_size == params["pixelsize"]:
        return {"status": "ok"}
    else:
        return {"status": "failed",
                "message": "The raster pixel size is {:s} m, {:s} m is allowed.".format(str(x_size), str(params["pixelsize"]))}
