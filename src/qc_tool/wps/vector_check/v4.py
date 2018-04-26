#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CRS check.
"""

import ogr
import re
import osr

from registry import register_check_function


@register_check_function(__name__, "CRS of layer expressed as EPSG code match reference EPSG code.")
def run_check(filepath, params):
    """
    CRS check.
    :param filepath: pathname to data source
    :param params: configuration
    :return: status + message
    """

    print("run_check.filepath={:s}".format(repr(filepath)))
    print("run_check.params={:s}".format(repr(params)))

    def check_crs(lyr):

        # get Spatial Reference and EPSG code
        srs = osr.SpatialReference(lyr.GetSpatialRef().ExportToWkt())
        if srs.IsProjected:
            epsg = srs.GetAttrValue("AUTHORITY", 1)
        else:
            return {"status": "failed",
                    "message": "the data is not projected"}

        # CRS check via EPSG comparison
        if epsg in map(str, params["epsg"]):
            return {"status": "ok",
                    "message": "the CRS check was successful"}
        else:
            return {"status": "failed",
                    "message": "forbidden EPSG code: {:s}".format(str(epsg))}

    # open source data, get list of matching layernames
    dsopen = ogr.Open(filepath)
    regex = re.compile(params["layer_regex"])
    layers_prefix = [layer.GetName() for layer in dsopen if params["layer_prefix"] in layer.GetName()]
    layers_regex = [layer for layer in layers_prefix if bool(regex.match(layer.lower()))]
    if not list(set(layers_prefix) - set(layers_regex)) and not len(layers_regex) == int(params["layer_count"]):
        return {"status": "failed",
                "message": "Number of matching layers {:d} does not correspond with declared number of layers({:d})".format(
                    len(layers_regex), int(params["layer_count"]))}

    # check CRS of all matching layers
    res = dict()
    for layername in layers_regex:
        layer = dsopen.GetLayerByName(layername)
        res[layername] = check_crs(layer)

    # return results for particular layers
    if "failed" not in list(set(([res[ln]["status"] for ln in res]))):
        return {"status": "ok",
                "message": "the CRS check was successful"}
    else:
        layer_results = ', '.join(
            "layer {!s}: {!r}".format(key, val) for (key, val) in {ln: res[ln]["message"] for ln in res}.items())

        res_message = "the CRS check failed {:s}".format(layer_results)
        return {"status": "failed",
                "message": res_message}
