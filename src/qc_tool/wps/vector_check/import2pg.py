#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Import layers into PostGIS db.
"""

from subprocess import run

from qc_tool.wps.helper import check_name
from qc_tool.wps.registry import register_check_function
from qc_tool.wps.vector_check.dump_gdbtable import get_fc_path


@register_check_function(__name__, "Import layers into PostGIS db.")
def run_check(filepath, params):
    """
    Import layers into PostGIS db. also imports the qc functions.
    :param filepath: pathname to data source
    :param params: configuration
    :return: status + message
    """

    connection_manager = params["connection_manager"]
    dsn, schema = connection_manager.get_dsn_schema()

    lyrs = get_fc_path(filepath)
    layer_regex = params["layer_regex"].replace("countrycode", params["country_codes"]).lower()
    layers_regex = [layer for layer in lyrs if check_name(layer.lower(), layer_regex)]

    if not layers_regex:
        return {"status": "aborted",
                "message": "There is no matching layer in the data source."}

    for lyr in layers_regex:
        pc = run(["ogr2ogr",
                   "-overwrite",
                   "-skipfailures",
                   "-f", "PostgreSQL",
                   "-lco", "SCHEMA={:s}".format(schema),
                   "PG:{:s}".format(dsn),
                   filepath,
                   lyr.split("/")[1]])
        if pc.returncode != 0:
            return {"status": "aborted",
                    "message": "Importing of {:s} layer into PostGIS db failed.".format(lyr)}
    return {"status": "ok"}
