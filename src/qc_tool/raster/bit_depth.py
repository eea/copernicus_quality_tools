#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from osgeo import gdal

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    # read the datatype parameter
    expected_datatype = params["datatype"]

    # open the file
    ds = gdal.Open(str(params["filepath"]))

    # get the DataType of the band ("Byte" means 8-bit depth)
    band = ds.GetRasterBand(1)
    actual_datatype = gdal.GetDataTypeName(band.DataType)

    # compare actual data type to expected data expected_type
    if str(actual_datatype).lower() != str(expected_datatype).lower():
        status.failed("The raster data type '{:s}' does not match the expected data type '{:s}'."
                      .format(actual_datatype, expected_datatype))
