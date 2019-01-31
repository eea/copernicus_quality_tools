#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from osgeo import gdal

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    # enable gdal to use exceptions
    gdal.UseExceptions()

    # file extension check
    ds_extension = params["filepath"].suffix
    if ds_extension not in params["formats"]:
        status.aborted("The source file has forbidden extension: {:s}.".format(ds_extension))
        return

    # try to open file with ogr drivers
    if ds_extension in params["drivers"]:
        try:
            ds_open = gdal.Open(str(params["filepath"]))
            if ds_open is None:
                status.aborted("The source file can not be opened.")
                return
        except:
            status.aborted("The source file can not be opened.")
            return

        # check file format
        drivername = ds_open.GetDriver().ShortName
        if drivername == params["drivers"][ds_extension]:
            return
        else:
            status.aborted("The file format is invalid.")
            return
    else:
        status.aborted("The source file has forbidden extension: {:s}".format(ds_extension))
        return
