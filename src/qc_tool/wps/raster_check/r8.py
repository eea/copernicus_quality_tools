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

    ds = gdal.Open(str(params["filepath"]))

    # get raster metadata
    meta = ds.GetMetadata("IMAGE_STRUCTURE")

    compression = meta.get("COMPRESSION", None)

    if compression is None:
        status.failed("The raster data compression is not set.")
        return

    if compression.lower() not in allowed_compression_types:
        status.failed("The raster compression type '{:s}' is not allowed.".format(compression))
