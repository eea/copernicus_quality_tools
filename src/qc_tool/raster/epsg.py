#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Raster uses specific EPSG code."
IS_SYSTEM = False


def run_check(params, status):
    import osgeo.gdal as gdal
    import osgeo.osr as osr

    from qc_tool.raster.helper import do_raster_layers

    for layer_def in do_raster_layers(params):
        ds = gdal.Open(str(layer_def["src_filepath"]))

        srs = osr.SpatialReference(ds.GetProjection())
        if srs is None or srs.IsProjected() == 0:
            status.failed("The raster {:s} has no projected coordinate system associated."
                          .format(layer_def["src_layer_name"]))
            continue

        # Search EPSG authority code
        srs.AutoIdentifyEPSG()
        authority_name = srs.GetAuthorityName(None)
        authority_code = srs.GetAuthorityCode(None)

        if authority_name == "EPSG" and authority_code is not None:
            # compare EPSG code using the root-level EPSG authority
            if authority_code not in map(str, params["epsg"]):
                status.aborted("Layer {:s} has illegal EPSG code {:s}."
                               .format(layer_def["src_layer_name"], str(authority_code)))
        else:
            status.aborted("Layer {:s} does not have an epsg code, srs: {:s}."
                           .format(layer_def["src_layer_name"], srs.ExportToWkt()))
