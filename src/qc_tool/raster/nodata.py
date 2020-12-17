#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Raster has a NoData value set."
IS_SYSTEM = False


def run_check(params, status):
    import osgeo.gdal as gdal
    from qc_tool.raster.helper import do_raster_layers

    for layer_def in do_raster_layers(params):
        ds = gdal.Open(str(layer_def["src_filepath"]))

        # get dictionary of pixel 'codes-counts'
        ds_band = ds.GetRasterBand(1)
        band_nodata = ds_band.GetNoDataValue()

        if band_nodata is None:
            status.aborted("Layer {:s} does not have a NoData value set."
                           .format(layer_def["src_layer_name"]))
        elif band_nodata != params["nodata_value"]:
            status.aborted("Layer {:s} has invalid NoData value: {}. The expected NoData value is {}."
                           .format(layer_def["src_layer_name"], band_nodata, params["nodata_value"]))
