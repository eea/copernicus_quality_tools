#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from osgeo import ogr
from osgeo import osr

from qc_tool.wps.helper import do_layers
from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    for layer_def in do_layers(params):
        ds = ogr.Open(str(layer_def["src_filepath"]))
        layer = ds.GetLayerByName(layer_def["src_layer_name"])
        srs = layer.GetSpatialRef()
        if srs is None:
            status.aborted()
            status.add_message("Layer {:s} has missing spatial reference system.".format(layer_def["src_layer_name"]))
            return

        # Search EPSG authority code
        authority_name = srs.GetAuthorityName(None)
        authority_code = srs.GetAuthorityCode(None)
        if authority_name != "EPSG":
            status.add_message("Layer {:s} has missing EPSG authority.".format(layer_def["src_layer_name"]))
            status.aborted()
            return
        if authority_code is None:
            status.add_message("Layer {:s} has missing EPSG code.".format(layer_def["src_layer_name"]))
            status.aborted()
            return

        # Compare EPSG code against boundary EPSG code.
        if "boundary" not in params["layer_defs"]:
            status.add_message("Check cancelled due to missing boundary.", failed=False)
            status.cancelled()
            return
        ds = ogr.Open(str(params["layer_defs"]["boundary"]["src_filepath"]))
        layer = ds.GetLayerByName(params["layer_defs"]["boundary"]["src_layer_name"])
        srs = layer.GetSpatialRef()
        boundary_authority_code = srs.GetAuthorityCode(None)
        if authority_code != boundary_authority_code:
            status.add_message("Check cancelled while the layer {:s} has epsg code {:s} different from boundary epsg code {:s}."
                               .format(layer_def["src_layer_name"], authority_code, boundary_authority_code))
            status.cancelled()
            return
        status.add_params({"layer_srs_epsg": int(authority_code)})
