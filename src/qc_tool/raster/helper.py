#!/usr/bin/env python3

from zipfile import ZipFile


def do_raster_layers(params):
    return [params["raster_layer_defs"][layer_alias] for layer_alias in params["layers"]]
