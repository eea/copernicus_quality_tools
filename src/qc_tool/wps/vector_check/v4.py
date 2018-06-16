#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CRS check.
"""

from osgeo import ogr
from osgeo import osr

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__, "CRS of layer expressed as EPSG code match reference EPSG code.")
def run_check(filepath, params):
    """
    CRS check.
    :param filepath: pathname to data source
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
                    "message": "The source data is not projected."}
        if epsg is None:
            return {"status": "failed",
                    "message": "The file has EPSG authority missing."}
        # CRS check via EPSG comparison
        if epsg in map(str, params["epsg"]):
            return {"status": "ok"}
        else:
            return {"status": "failed",
                    "message": "EPSG code {:s} is not in applicable codes {:s}.".format(str(epsg), str(params["epsg"]))}

    # check CRS of all matching layers
    res = dict()
    dsopen = ogr.Open(filepath)
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
                "message": res_message}
