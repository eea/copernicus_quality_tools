#!/bin/env python3
# -*- coding: utf-8 -*-


import re

from qc_tool.wps.helper import do_layers
from qc_tool.wps.helper import get_failed_items_message
from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    cursor = params["connection_manager"].get_connection().cursor()

    if "boundary" not in params["layer_defs"]:
        status.cancelled()
        status.add_message("Check cancelled due to boundary not being available.", failed=False)
        return

    for layer_def in do_layers(params):
        # Prepare parameters used in sql clauses.
        sql_params = {"layer_name": layer_def["pg_layer_name"],
                      "boundary_name": params["layer_defs"]["boundary"]["pg_layer_name"],
                      "boundary_unit_column_name": params["boundary_unit_column_name"],
                      "error_table": "v10_{:s}_error".format(layer_def["pg_layer_name"]),
                      "warning_table": "v10_{:s}_warning".format(layer_def["pg_layer_name"])}

        # Create table of error items.
        sql = ("CREATE TABLE {error_table} AS"
               " WITH"
               "  boundary_union AS (SELECT {boundary_unit_column_name}, ST_Union(wkb_geometry) AS geom"
               "                     FROM {boundary_name}"
               "                     WHERE {boundary_unit_column_name} IN (SELECT {boundary_unit_column_name}"
               "                                                           FROM {layer_name})"
               "                     GROUP BY {boundary_unit_column_name}),"
               "  layer_union AS (SELECT {boundary_unit_column_name}, ST_Union(wkb_geometry) AS geom"
               "                  FROM {layer_name}"
               "                  GROUP BY {boundary_unit_column_name})"
               " SELECT"
               "  layer_union.{boundary_unit_column_name},"
               "  (ST_Dump(ST_Difference(boundary_union.geom, layer_union.geom))).geom AS geom"
               " FROM layer_union"
               " INNER JOIN boundary_union USING ({boundary_unit_column_name});")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report error items.
        if cursor.rowcount > 0:
            message = "The layer {:s} has {:d} gap(s).".format(layer_def["pg_layer_name"], cursor.rowcount)
            status.add_message(message)
            status.add_full_table(sql_params["error_table"])

        # Find warning features.
        sql = ("CREATE TABLE {warning_table} AS"
               " SELECT layer.{boundary_unit_column_name}, layer.wkb_geometry"
               " FROM {layer_name} AS layer"
               " WHERE layer.{boundary_unit_column_name} IS NULL"
               "  OR layer.{boundary_unit_column_name} NOT IN (SELECT {boundary_unit_column_name} FROM {boundary_name});")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report warning items.
        if cursor.rowcount > 0:
            message = "The layer {:s} has {:d} feature(s) of unknown boundary unit.".format(layer_def["pg_layer_name"], cursor.rowcount)
            status.add_message(message, failed=False)
            status.add_full_table(sql_params["warning_table"])
