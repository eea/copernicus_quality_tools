#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Bit depth check
"""


from osgeo import gdal

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params):
    """
    Bit depth / data type check.
    :param params: configuration with a bitdepth parameter
    :return: status + message
    """

    # read the datatype parameter
    expected_datatype = params["datatype"]

    # open the file
    ds = gdal.Open(str(params["filepath"]))

    if ds is None:
        return {"status": "aborted",
                "messages": ["The raster {:s} could not be opened.".format(params["filepath"].name)]}

    # get the number of bands
    num_bands = ds.RasterCount
    if num_bands != 1:
        return {"status": "failed",
                "messages": ["The raster has {:d} bands."
                             "The expected number of bands is one.".format(num_bands)]}

    # get the DataType of the band ("Byte" means 8-bit depth)
    band = ds.GetRasterBand(1)
    actual_datatype = gdal.GetDataTypeName(band.DataType)

    # compare actual data type to expected data excpected_type
    if str(actual_datatype).lower() == str(expected_datatype).lower():
        return {"status": "ok"}
    else:
        return {"status": "failed",
                "messages": ["The raster data type '{:s}' does not match"
                             " the expected data type '{:s}'.".format(actual_datatype, expected_datatype)]}
