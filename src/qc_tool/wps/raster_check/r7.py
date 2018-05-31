#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Bit depth check
"""

import ogr

from qc_tool.wps.registry import register_check_function

@register_check_function(__name__, "Raster has specified bit depth data type")
def run_check(filepath, params):
    """
    Bit depth / data type check.
    :param filepath: pathname to data source
    :param params: configuration with a bitdepth parameter
    :return: status + message
    """

    # read the datatype parameter
    expected_datatype = params["datatype"]

    # open the file
    ds = gdal.Open(filepath)

    if ds is None:
        return {"status": "aborted",
                "message": "The raster {:s} could not be opened.".format(filepath)}

    # get the number of bands
    num_bands = ds.RasterCount
    if num_bands != 1:
        return {"status": "failed",
                "message": "The raster has {:d} bands. \
                expected number of bands is one.".format(num_bands)}

    band = ds.GetRasterBand(1)
    actual_datatype = gdal.GetDataTypeName(band.DataType)

    # compare actual data type to expected data excpected_type
    if str(actual_datatype).lower() == str(expected_datatype).lower():
        return {"status": "ok"}
    else:
        return {"status": "failed",
                "message": "The raster data type'{:s}' does not match  the \
                            expected data type '{:s}'".format(actual_datatype, expected_datatype)}
