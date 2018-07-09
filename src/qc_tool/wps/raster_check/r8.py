#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Compression type check.
"""


from osgeo import gdal

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params):
    """
    Compression type check.
    :param params: configuration
    :return: status + message
    """

    # enable gdal to use exceptions
    gdal.UseExceptions()

    # set compression type names to lowercase
    allowed_compression_types = [c.lower() for c in params["compression"]]

    try:
        ds_open = gdal.Open(str(params["filepath"]))
        if ds_open is None:
            return {"status": "failed",
                    "messages": ["The file can not be opened."]}
    except:
        return {"status": "failed",
                "messages": ["The file can not be opened."]}

    # get raster metadata
    meta = ds_open.GetMetadata('IMAGE_STRUCTURE')

    compression = meta.get('COMPRESSION', None)

    if compression is None:
        return {"status": "failed",
                "messages": ["The raster data compression is not set."]}

    if compression.lower() in allowed_compression_types:
        return {"status": "ok"}

    else:
        return {"status": "failed",
                "messages": ["The raster compression type '{:s}' is not allowed.".format(compression)]}
