#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from osgeo import ogr
from osgeo import osr

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    for layer_name, layer_filepath in params["layer_sources"]:
        ds = ogr.Open(str(layer_filepath))
        layer = ds.GetLayerByName(layer_name)
        srs = osr.SpatialReference(layer.GetSpatialRef().ExportToWkt())
        if not srs.IsProjected:
            status.add_message("Layer {:s} has source data are not projected.".format(layer_name))
        else:
            epsg = srs.GetAttrValue("AUTHORITY", 1)

            # special case for ETRS_1989_LAEA: epsg code should be 3035
            if epsg is None:
                projcs = srs.GetAttrValue("PROJCS")
                if projcs == "ETRS_1989_LAEA":
                    epsg = 3035

            if epsg is None:
                status.add_message("Layer {:s} has missing EPSG authority.".format(layer_name))
            elif epsg not in map(str, params["epsg"]):
                status.add_message("Layer {:s} has illegal EPSG code {:s}.".format(layer_name, str(epsg)))
