#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from osgeo import gdal

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    # enable gdal to use exceptions
    gdal.UseExceptions()

    # set compression type names to lowercase
    allowed_compression_types = [c.lower() for c in params["compression"]]

    try:
        ds_open = gdal.Open(str(params["filepath"]))
        if ds_open is None:
            status.add_message("The file can not be opened.")
            return
    except:
        status.add_message("The file can not be opened.")
        return

    # get raster metadata
    meta = ds_open.GetMetadata('IMAGE_STRUCTURE')

    compression = meta.get('COMPRESSION', None)

    if compression is None:
        status.add_message("The raster data compression is not set.")
        return

    if compression.lower() in allowed_compression_types:
        return
    else:
        status.add_message("The raster compression type '{:s}' is not allowed.".format(compression))
        return
