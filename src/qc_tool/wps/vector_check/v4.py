#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CRS check.
"""


from osgeo import ogr
from osgeo import osr

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params):
    """
    CRS check.
    :param params: configuration
    :return: status + message
    """
    def check_crs(lyr):
        # get Spatial Reference and EPSG code
        srs = osr.SpatialReference(lyr.GetSpatialRef().ExportToWkt())
        if srs.IsProjected:
            epsg = srs.GetAttrValue("AUTHORITY", 1)
        else:
            return {"status": "failed",
                    "messages": ["The source data is not projected."]}
        if epsg is None:
            return {"status": "failed",
                    "messages": ["The file has EPSG authority missing."]}
        # CRS check via EPSG comparison
        if epsg in map(str, params["epsg"]):
            return {"status": "ok"}
        else:
            return {"status": "failed",
                    "messages": ["EPSG code {:s} is not in"
                                 " applicable codes {:s}.".format(str(epsg), str(params["epsg"]))]}

    # check CRS of all matching layers
    res = dict()
    dsopen = ogr.Open(str(params["filepath"]))
    for layername in params["layer_names"]:
        layer = dsopen.GetLayerByName(layername)
        res[layername] = check_crs(layer)

    # return results for particular layers
    if "failed" not in list(set(([res[ln]["status"] for ln in res]))):
        return {"status": "ok"}
    else:
        layer_results = ', '.join(
            "layer {!s}: {!r}".format(key, val) for (key, val) in {ln: res[ln]["message"] for ln in res}.items())

        res_message = "The CRS check failed ({:s}).".format(layer_results)
        return {"status": "failed",
                "messages": [res_message]}
