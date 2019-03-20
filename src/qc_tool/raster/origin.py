#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Bounding box upper left corner is positioned on grid."
IS_SYSTEM = False


def run_check(params, status):
    import osgeo.gdal as gdal
    from qc_tool.raster.helper import do_raster_layers

    for layer_def in do_raster_layers(params):
        ds = gdal.Open(str(layer_def["src_filepath"]))

        # upper-left coordinate divided by pixel-size must leave no remainder
        gt = ds.GetGeoTransform()
        ulx = gt[0]
        uly = gt[3]
        pixelsizex = gt[1]
        pixelsizey = gt[5]

        if ulx % pixelsizex != 0 or uly % pixelsizey != 0:
            status.failed("The upper-left X, Y coordinates of layer {:s} are not divisible by pixel-size with no remainder."
                          .format(layer_def["src_layer_name"]))

            # Pan-European layers must fit to the LEAC 1 km grid
            if "_eu_" in layer_def["src_layer_name"]:
                if ulx % 1000 != 0 or uly % 1000 != 0:
                    status.failed("The raster origin of layer {:s} does not fit to the LEAC 1 km grid."
                                  .format(layer_def["src_layer_name"]))
