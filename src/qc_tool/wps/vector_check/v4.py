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
            status.aborted("Layer {:s} has missing spatial reference system.".format(layer_def["src_layer_name"]))
            return

        # Search EPSG authority code
        authority_name = srs.GetAuthorityName(None)
        authority_code = srs.GetAuthorityCode(None)

        if authority_name == "EPSG" and authority_code is not None:
            # compare EPSG code using the root-level EPSG authority in the SRS WKT of the layer.
            if authority_code in map(str, params["epsg"]):
                status.add_params({"layer_srs_epsg": int(authority_code)})
            else:
                status.aborted("Layer {:s} has illegal EPSG code {:s}.".format(layer_def["src_layer_name"], str(authority_code)))
        elif "auto_identify_epsg" in params and params["auto_identify_epsg"] == True:
            # setting auto_identify_epsg can be used for less-strict checking of .prj files without EPSG authority (from ESRI SW)
            # there is a built-in function in GDAL 2.3 with similar SRS matching logic.
            # If the EPSG code is not detected, this code tries to compare if the actual and expected SRS instances represent
            # the same spatial reference system. The default setting of auto_identify_epsg is False.
            allowed_codes = params["epsg"]
            for allowed_code in allowed_codes:
                expected_srs = osr.SpatialReference()
                expected_srs.ImportFromEPSG(allowed_code)
                if srs.IsSame(expected_srs):
                    status.add_params({"layer_srs_epsg": int(allowed_code)})
        else:
            # the setting is strict and no EPSG code has been found in the SRS of the layer.
            status.aborted("The SRS of the layer {:s} does not have an EPSG code specified."
                           " Detected SRS: {:s}"
                           .format(layer_def["src_layer_name"], srs.ExportToWkt()))
