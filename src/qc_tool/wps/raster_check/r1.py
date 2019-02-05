#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from osgeo import gdal

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):

    # file extension check
    ds_extension = params["filepath"].suffix
    if ds_extension not in params["formats"]:
        status.aborted("The source file has forbidden extension: {:s}.".format(ds_extension))
        return

    # try to open file with GDAL
    ds = gdal.Open(str(params["filepath"]))
    if ds is None:
        status.aborted("The source file {:s} can not be opened.".format(params["filepath"].name))
        return

    # check file format
    drivername = ds.GetDriver().ShortName
    if drivername != params["drivers"][ds_extension]:
        status.aborted("The raster {:s} does is not in expected {:s} file format."
                       .format(params["filepath"].name, params["drivers"][ds_extension]))
        return

    # check number of bands. One band is allowed.
    num_bands = ds.RasterCount
    if num_bands != 1:
        status.aborted("The raster {:s} has {:d} bands. The expected number of bands is one."
                       .format(params["filepath"].name, num_bands))
        return
