#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Pixel has specific size."
IS_SYSTEM = False


def run_check(params, status):
    import osgeo.gdal as gdal

    from qc_tool.raster.helper import do_raster_layers

    for layer_def in do_raster_layers(params):
        ds = gdal.Open(str(layer_def["src_filepath"]))

        # get raster pixel size
        gt = ds.GetGeoTransform()
        x_size = abs(gt[1])
        y_size = abs(gt[5])

        # verify the square shape of the pixel
        if x_size != y_size:
            status.failed("The pixel is not square-shaped.")
            return

        if x_size != params["pixelsize"]:
            status.failed("Layer {:s} has raster pixel size {:d} m, {:d} m is allowed."
                          .format(layer_def["src_layer_name"], x_size, params["pixelsize"]))
