#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "EPSG codes of the layers match EPSG code of the boundary layer."
IS_SYSTEM = False


def run_check(params, status):
    import osgeo.ogr as ogr
    import osgeo.osr as osr

    from qc_tool.vector.helper import do_layers

    for layer_def in do_layers(params):
        ds = ogr.Open(str(layer_def["src_filepath"]))
        layer = ds.GetLayerByName(layer_def["src_layer_name"])
        srs = layer.GetSpatialRef()
        if srs is None:
            status.aborted("Layer {:s} has missing spatial reference system.".format(layer_def["src_layer_name"]))
            return

        # Search EPSG authority code
        authority_name = srs.GetAuthorityName(None)
        authority_code = srs.GetAuthorityCode(None)
        if authority_name != "EPSG":
            status.failed("Layer {:s} has missing EPSG authority.".format(layer_def["src_layer_name"]))
            return
        if authority_code is None:
            status.failed("Layer {:s} has missing EPSG code.".format(layer_def["src_layer_name"]))
            return

        # Compare EPSG code against boundary EPSG code.
        if "boundary" not in params["layer_defs"]:
            status.cancelled("Check cancelled due to missing boundary.")
            return
        ds = ogr.Open(str(params["layer_defs"]["boundary"]["src_filepath"]))
        layer = ds.GetLayerByName(params["layer_defs"]["boundary"]["src_layer_name"])
        srs = layer.GetSpatialRef()
        boundary_authority_code = srs.GetAuthorityCode(None)
        if authority_code != boundary_authority_code:
            status.cancelled("Check cancelled while layer {:s} has epsg code {:s} different from boundary epsg code {:s}."
                             .format(layer_def["src_layer_name"], authority_code, boundary_authority_code))
            return
        status.add_params({"layer_srs_epsg": int(authority_code)})
