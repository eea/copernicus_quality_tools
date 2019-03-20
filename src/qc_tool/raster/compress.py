#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Raster uses specific compression formats."
IS_SYSTEM = False


def run_check(params, status):
    import osgeo.gdal as gdal
    from qc_tool.raster.helper import do_raster_layers

    # enable gdal to use exceptions
    gdal.UseExceptions()

    # set compression type names to lowercase
    allowed_compression_types = [c.lower() for c in params["compression"]]

    for layer_def in do_raster_layers(params):
        ds = gdal.Open(str(layer_def["src_filepath"]))

        # get raster metadata
        meta = ds.GetMetadata("IMAGE_STRUCTURE")

        compression = meta.get("COMPRESSION", None)

        if compression is None:
            status.failed("Layer {:s} does not have raster data compression set.".format(layer_def["src_layer_name"]))
            continue

        if compression.lower() not in allowed_compression_types:
            status.failed("The raster compression type '{:s}' of layer {:s} is not allowed."
                          .format(compression, layer_def["src_layer_name"]))
