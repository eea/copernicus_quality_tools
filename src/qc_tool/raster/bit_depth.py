#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Raster datatype is of specific bit depth."
IS_SYSTEM = False


def run_check(params, status):
    import osgeo.gdal as gdal
    from qc_tool.raster.helper import do_raster_layers

    expected_datatype = params["datatype"]

    for layer_def in do_raster_layers(params):
        ds = gdal.Open(str(layer_def["src_filepath"]))

        # Get the DataType of the band ("Byte" means 8-bit depth).
        band = ds.GetRasterBand(1)
        actual_datatype = gdal.GetDataTypeName(band.DataType)

        # Compare actual data type to expected data type.
        if str(actual_datatype).lower() != str(expected_datatype).lower():
            status.failed("Layer {:s}: The raster data type '{:s}' does not match the expected data type '{:s}'."
                          .format(layer_def["src_layer_name"], actual_datatype, expected_datatype))
