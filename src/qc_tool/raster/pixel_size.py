#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from osgeo import gdal


def run_check(params, status):

    ds_open = gdal.Open(str(params["filepath"]))

    # get raster pixel size
    gt = ds_open.GetGeoTransform()
    x_size = abs(gt[1])
    y_size = abs(gt[5])

    # verify the square shape of the pixel
    if x_size != y_size:
        status.failed("The pixel is not square-shaped.")
        return

    if x_size != params["pixelsize"]:
        status.failed("The raster pixel size is {:d} m, {:d} m is allowed."
                      .format(x_size, params["pixelsize"]))
