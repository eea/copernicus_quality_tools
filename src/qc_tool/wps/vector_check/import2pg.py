#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Import layers into PostGIS db.
"""


from subprocess import Popen, PIPE

import psycopg2

from qc_tool.wps.helper import check_name
from qc_tool.wps.registry import register_check_function
from qc_tool.wps.vector_check.dump_gdbtable import get_fc_path


@register_check_function(__name__, "Import layers into PostGIS db.")
def run_check(filepath, params):
    """
    Import layers into PostGIS db.
    :param filepath: pathname to data source
    :param params: configuration
    :return: status + message
    """

    dsn, schema = params["connection_manager"].get_dsn_schema()

    lyrs = get_fc_path(filepath)
    layer_regex = params["layer_regex"].replace("countrycode", params["country_codes"]).lower()
    layers_regex = [layer for layer in lyrs if check_name(layer.lower(), layer_regex)]

    if not layers_regex:
        return {"status": "aborted",
                "message": "There is no matching layer in the data source."}

    for lyr in layers_regex:
        p = Popen(["ogr2ogr",
                   "-overwrite",
                   "-skipfailures",
                   "-f", "PostgreSQL",
                   "PG:{:s} active_schema={:s}".format(dsn, schema),
                   filepath,
                   lyr.split("/")[1]])
        if p.returncode != 0 and p.returncode is not None:
            return {"status": "aborted",
                    "message": "Importing of {:s} layer into PostGIS db failed with error: {:s}".format(
                        lyr, p.communicate()[1])}
    return {"status": "ok"}
