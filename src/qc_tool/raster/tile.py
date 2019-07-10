#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Raster is tiled."
IS_SYSTEM = False


def run_check(params, status):
    import osgeo.gdal as gdal
    from qc_tool.raster.helper import do_raster_layers

    for layer_def in do_raster_layers(params):
        ds = gdal.Open(str(layer_def["src_filepath"]))

        # get dictionary of pixel 'codes-counts'
        ds_band = ds.GetRasterBand(1)
        blocksize = ds_band.GetBlockSize()
        if blocksize[0] > params["max_blocksize"] or blocksize[1] > params["max_blocksize"]:
            status.aborted("Layer {:s} has block size [{:d}, {:d}]. "
                           "Maximum allowed block height or width is {:d}."
                           .format(layer_def["src_layer_name"], blocksize[0], blocksize[1],
                                   params["max_blocksize"]))
