#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from osgeo import ogr
from osgeo import osr

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    for layer_info in params["layer_aliases"].values():
        ds = ogr.Open(str(layer_info["src_filepath"]))
        layer = ds.GetLayerByName(layer_info["src_layer_name"])
        srs = layer.GetSpatialRef()
        if srs is None:
            status.aborted()
            status.add_message("Layer {:s} has missing spatial reference system.".format(layer_info["src_layer_name"]))
            return

        # Search EPSG authority code
        authority_name = srs.GetAuthorityName(None)
        authority_code = srs.GetAuthorityCode(None)

        if authority_name == "EPSG" and authority_code is not None:
            # compare EPSG code using the root-level EPSG authority in the SRS WKT of the layer.
            if authority_code in map(str, params["epsg"]):
                status.add_params({"layer_srs_epsg": int(authority_code)})
                return
            else:
                status.aborted()
                status.add_message("Layer {:s} has illegal EPSG code {:s}.".format(layer_info["src_layer_name"], str(authority_code)))
                return
        else:
            # FIXME this code is necessary for checking .shp files without EPSG authority in the .prj (from ESRI SW)
            # there is a built-in function in GDAL 2.3 with similar SRS matching logic.
            # If the EPSG code is not detected, try to compare if the actual and expected SRS instances represent
            # the same spatial reference system.
            allowed_codes = params["epsg"]
            for allowed_code in allowed_codes:
                expected_srs = osr.SpatialReference()
                expected_srs.ImportFromEPSG(allowed_code)
                if srs.IsSame(expected_srs):
                    status.add_params({"layer_srs_epsg": int(allowed_code)})
                    return

        # If we reached until this spot, no matching EPSG code or matching SRS instance could be found.
        status.aborted()
        status.add_message("The SRS of Layer {:s} is not in the list of allowed spatial reference systems. "
                           "detected SRS: {:s}, "
                           "list of allowed SRS's: {:s}.".format(layer_info["src_layer_name"],
                                                                 srs.ExportToWkt(),
                                                                 ", ".join(map(str, params["epsg"]))))
