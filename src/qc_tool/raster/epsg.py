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
            status.failed("The raster {:s} has SRS missing.".format(layer_def["src_layer_name"]))
            continue

        # Search EPSG authority code
        srs.AutoIdentifyEPSG()
        authority_name = srs.GetAuthorityName(None)
        authority_code = srs.GetAuthorityCode(None)

        if authority_name == "EPSG" and authority_code is not None:
            try:
                authority_code = int(authority_code)
            except ValueError:
                status.aborted("The raster {:s} has non integer epsg code {:s}".format(layer_def["src_layer_name"], authority_code))
            else:
                if authority_code != params["epsg"]:
                    status.aborted("The raster {:s} has illegal EPSG code {:d}."
                                   .format(layer_def["src_layer_name"], authority_code))
        else:
            status.aborted("The raster {:s} has epsg code missing, srs: {:s}."
                           .format(layer_def["src_layer_name"], srs.ExportToWkt()))
