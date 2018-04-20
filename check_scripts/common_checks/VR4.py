#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CRS check.
"""

import os
import ogr
import osr
import gdal

__author__ = "Jiri Tomicek"
__copyright__ = "Copyright 2018, GISAT s.r.o., CZ"
__email__ = "jiri.tomicek@gisat.cz"
__status__ = "testing"

parametry = {"check_id": "R4", "check_name": "coordinate reference system (CRS)", "parameters": [{"name": "EPSG", "value": ["3035"], "exceptions": []}]}
data_source_vector = "/home/jtomicek/GISAT/GitHub/copernicus_quality_tools/testing_data/clc2012_mt.gdb"
data_source_raster = "/home/jtomicek/Dropbox/COP15/water_bodies_raster/WAW_2015_100m_eu_03035_d02_full/WAW_2015_100m_eu_03035_d02_full.tif"

def run_check(params, ds, chtype, ln=None):
    """
    CRS check.
    :param params: Parameters from config.json file
    :param ds: pathname to data source
    :param chtype: type of check ('v' for vector check, 'r' for raster check)
    :param ln: name of the layer in data source (default as None)
    :return: status + message
    """

    # enable gdal/ogr to use exceptions
    gdal.UseExceptions()
    ogr.UseExceptions()

    # create dict of params
    p = dict()
    for d in params["parameters"]:
        p[d["name"]] = [d["value"], d["exceptions"]]

    if len(p) != 1:
        return {"STATUS": "WARNING",
                "MESSAGE": "V4/R4 CHECK TAKES EXACTLY 1 INPUT PARAMETER (%d GIVEN)" % len(p)}

    # try to open data
    vector_data, raster_data = False, False
    if chtype.lower() == "v":
        try:
            dsopen = ogr.Open(ds)
            if dsopen is None:
                vector_data = False
            vector_data = True
        except:
            vector_data = False

    elif chtype.lower() == "r":
        try:
            dsopen = gdal.Open(ds)
            if dsopen is None:
                raster_data = False
            raster_data = True
        except:
            raster_data = False

    if raster_data is False and vector_data is False:
        return {"status": "FAILED",
                "message": "UNSUPPORTED DATA FORMAT"}

    # get Spatial Reference and EPSG code
    epsg = None
    if vector_data and not raster_data:
        layer = dsopen.GetLayer(ln)
        srs = osr.SpatialReference(layer.GetSpatialRef().ExportToWkt())
        if srs.IsProjected:
            epsg = int(srs.GetAttrValue("AUTHORITY", 1))
        else:
            return {"status": "FAILED",
                    "message": "THE DATA IS NOT PROJECTED"}

    if not vector_data and raster_data:
        srs = osr.SpatialReference(dsopen.GetProjection())
        if srs.IsProjected:
            epsg = int(srs.GetAttrValue("AUTHORITY", 1))
        else:
            return {"status": "FAILED",
                    "message": "THE DATA IS NOT PROJECTED"}

    # get list of allowed EPSG codes from config. parameters
    allowed_epsgs = map(int, p["EPSG"][0])

    # CRS check via EPSG comparison
    if epsg in allowed_epsgs:
        return {"status": "OK",
                "message": "THE CRS CHECK WAS SUCCESSFUL"}
    else:
        return {"status": "FAILED",
                "message": "THE CRS CHECK FAILED: FORBIDDEN EPSG CODE: %d" % epsg}
