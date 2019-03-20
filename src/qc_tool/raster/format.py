#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Delivery content uses specific file format."
IS_SYSTEM = False


def run_check(params, status):
    import osgeo.gdal as gdal
    from qc_tool.raster.helper import do_raster_layers

    filepaths = set(layer_def["src_filepath"] for layer_def in do_raster_layers(params))
    for src_filepath in filepaths:

        # file extension check
        ds_extension = src_filepath.suffix
        if ds_extension not in params["formats"]:
            status.aborted("The source file has forbidden extension: {:s}.".format(ds_extension))
            continue

        # try to open file with GDAL
        ds = gdal.Open(str(src_filepath))
        if ds is None:
            status.aborted("The source file {:s} can not be opened.".format(params["filepath"].name))
            continue

        # check file format
        drivername = ds.GetDriver().ShortName
        if drivername != params["drivers"][ds_extension]:
            status.aborted("The raster {:s} does is not in expected {:s} file format."
                           .format(src_filepath.name, params["drivers"][ds_extension]))
            continue

        # check number of bands. One band is allowed.
        num_bands = ds.RasterCount
        if num_bands != 1:
            status.aborted("The raster {:s} has {:d} bands. The expected number of bands is one."
                           .format(src_filepath.name, num_bands))
            continue
