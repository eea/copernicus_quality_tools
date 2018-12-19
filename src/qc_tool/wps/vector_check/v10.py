#!/bin/env python3
# -*- coding: utf-8 -*-


import re

from qc_tool.wps.helper import do_layers
from qc_tool.wps.helper import get_failed_items_message
from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    cursor = params["connection_manager"].get_connection().cursor()

    for layer_def in do_layers(params):
        # Prepare parameters used in sql clauses.
        sql_params = {"layer_name": layer_def["pg_layer_name"],
                      "boundary_name": params["layer_defs"]["boundary"]["pg_layer_name"],
                      "error_table": "v10_{:s}_error".format(layer_def["pg_layer_name"])}

        # Create table of error items.
        sql = ("CREATE TABLE {error_table} AS"
               " WITH"
               "  layer_union AS (SELECT ST_Union(wkb_geometry) AS geom FROM {layer_name}),"
               "  boundary_union AS (SELECT ST_Union(wkb_geometry) AS geom FROM {boundary_name})"
               " SELECT (ST_Dump(ST_Difference(ST_Transform(boundary_union.geom, ST_SRID(layer_union.geom)), layer_union.geom))).geom AS geom"
               " FROM layer_union, boundary_union;")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report error items.
        if cursor.rowcount > 0:
            message = "The layer {:s} has {:d} gaps.".format(layer_def["pg_layer_name"], cursor.rowcount)
            status.add_message(message)
            status.add_full_table(sql_params["error_table"])
