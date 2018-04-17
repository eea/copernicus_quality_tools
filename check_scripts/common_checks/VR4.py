#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""
CRS check.
"""

import os
import ogr
import json
import gdal

__author__ = "Jiri Tomicek"
__copyright__ = "Copyright 2018, GISAT s.r.o., CZ"
__email__ = "jiri.tomicek@gisat.cz"
__status__ = "testing"

parametry = {"check_id": "R4", "check_name": "coordinate reference system (CRS)", "parameters": [{"name": "EPSG", "value": ["3035"], "exceptions": []}]}
data_source_vector = "/home/jtomicek/GISAT/GitHub/copernicus_quality_tools/testing_data/clc2012_mt.gdb"
data_source_raster = "/home/jtomicek/Dropbox/COP15/water_bodies_raster/WAW_2015_100m_eu_03035_d02_full/WAW_2015_100m_eu_03035_d02_full.tif"



def run_check(params, ds):
    """
    CRS check.
    :param params: Parameters from config.json file
    :param ds: pathname to data source
    :return: status + message
    """

    # enable gdal/ogr to use exceptions
    gdal.UseExceptions()
    ogr.UseExceptions()

    # check for data source existence
    if not os.path.exists(ds):
        return {"STATUS": "FAILED",
                "MESSAGE": "FILE DOES NOT EXIST IN FILESYSTEM"}

    # create dict of params
    p = dict()
    for d in params["parameters"]:
        p[d["name"]] = [d["value"], d["exceptions"]]



print run_check(parametry, data_source_raster)