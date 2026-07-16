#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Raster uses specific EPSG code."
IS_SYSTEM = False


def run_check(params, status):
    import osgeo.gdal as gdal
    import osgeo.osr as osr

    from qc_tool.raster.helper import do_raster_layers

    aoi_code = params.get("aoi_code")
    extra_epsg_codes = params.get("extra_epsg_codes", {})
    expected_epsg = extra_epsg_codes.get(aoi_code, params["epsg"]) if aoi_code else params["epsg"]

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
                if authority_code != expected_epsg:
                    status.aborted("The raster {:s} has illegal EPSG code {:d}."
                                   .format(layer_def["src_layer_name"], authority_code))
        elif params.get("auto_identify_epsg", False):
            # Parameter auto_identify_epsg can be used for less-strict checking of .prj files.
            # There is a built-in function in GDAL 2.3 with matching logic.
            expected_srs = osr.SpatialReference()
            expected_srs.ImportFromEPSG(expected_epsg)
            if srs.IsSame(expected_srs):
                # The auto-detected epsg is made available for other checks.
                status.add_params({"detected_epsg": expected_epsg})
            else:
                status.aborted("The raster {:s} does not have an epsg code and the epsg code can not be detected, srs: {:s}."
                               .format(layer_def["src_layer_name"], srs.ExportToWkt()))
        else:
            status.aborted("The raster {:s} has epsg code missing, srs: {:s}."
                           .format(layer_def["src_layer_name"], srs.ExportToWkt()))
