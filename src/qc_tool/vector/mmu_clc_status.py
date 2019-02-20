#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import re

from qc_tool.vector.helper import do_layers
from qc_tool.vector.helper import get_failed_items_message


DESCRIPTION = "Minimum mapping unit, Corine Land Cover status layer."
IS_SYSTEM = False


def run_check(params, status):
    cursor = params["connection_manager"].get_connection().cursor()

    for layer_def in do_layers(params):
        # Prepare parameters used in sql clauses.
        sql_params = {"fid_name": layer_def["pg_fid_name"],
                      "layer_name": layer_def["pg_layer_name"],
                      "area_column_name": params["area_column_name"],
                      "area_m2": params["area_m2"],
                      "general_table": "v11_{:s}_general".format(layer_def["pg_layer_name"]),
                      "exception_table": "v11_{:s}_exception".format(layer_def["pg_layer_name"]),
                      "error_table": "v11_{:s}_error".format(layer_def["pg_layer_name"])}

        # Create table of general items.
        sql = ("CREATE TABLE {general_table} AS"
               " SELECT {fid_name}"
               " FROM {layer_name}"
               " WHERE"
               "  {area_column_name} >= {area_m2};")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Create table of exception items.
        sql = ("CREATE TABLE {exception_table} AS"
               " WITH"
               "  margin AS ("
               "   SELECT ST_Boundary(ST_Union(wkb_geometry)) AS geom"
               "   FROM {layer_name}),"
               "  layer AS ("
               "   SELECT *"
               "   FROM {layer_name}"
               "   WHERE"
               "    {fid_name} NOT IN (SELECT {fid_name} FROM {general_table}))"
               # Marginal features.
               " SELECT layer.{fid_name}"
               " FROM layer, margin"
               " WHERE"
               "  ST_Dimension(ST_Intersection(layer.wkb_geometry, margin.geom)) >= 1;")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report exception items.
        items_message = get_failed_items_message(cursor, sql_params["exception_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.info("Layer {:s} has exception features with {:s}: {:s}."
                        .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["exception_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

        # Create table of error items.
        sql = ("CREATE TABLE {error_table} AS"
               " SELECT {fid_name}"
               " FROM {layer_name}"
               " WHERE"
               "  {fid_name} NOT IN (SELECT {fid_name} FROM {general_table})"
               "  AND {fid_name} NOT IN (SELECT {fid_name} FROM {exception_table});")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report error items.
        items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.failed("Layer {:s} has error features with {:s}: {:s}."
                          .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])
