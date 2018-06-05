#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Compression type check.
"""

import gdal

from qc_tool.wps.registry import register_check_function

@register_check_function(__name__, "Compression type check.")
def run_check(filepath, params):
    """
    Compression type check.
    :param filepath: pathname to data source
    :param params: configuration
    :return: status + message
    """

    # enable gdal to use exceptions
    gdal.UseExceptions()

    # set compression type names to lowercase
    allowed_compression_types = [c.lower() for c in params["compression"]]
    print allowed_compression_types

    try:
        ds_open = gdal.Open(filepath)
        if ds_open is None:
            return {"status": "failed",
                    "message": "The file can not be opened."}
    except:
        return {"status": "failed",
                "message": "The file can not be opened."}

    # get raster metadata
    meta = ds_open.GetMetadata('IMAGE_STRUCTURE')
    print meta

    compression = meta.get('COMPRESSION', None)

    if compression is None:
        return {"status": "failed",
                "message": "The raster data compression is not set."}

    if compression.lower() in allowed_compression_types:
        return {"status": "ok"}

    else:
        return {"status": "failed",
                "message": "The raster compression type '{:s}' is not allowed.".format(compression)}
