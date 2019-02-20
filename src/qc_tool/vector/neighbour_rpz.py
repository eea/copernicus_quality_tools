#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import re

from qc_tool.wps.helper import do_layers
from qc_tool.wps.helper import get_failed_items_message


DESCRIPTION = "There is no couple of neighbouring polygons having the same code, Riparian zones."
IS_SYSTEM = False


def run_check(params, status):
    cursor = params["connection_manager"].get_connection().cursor()

    for layer_def in do_layers(params):
        # Prepare parameters used in sql clauses.
        sql_params = {"fid_name": layer_def["pg_fid_name"],
                      "layer_name": layer_def["pg_layer_name"],
                      "code_column_name": params["code_column_name"],
                      "general_table": "v14_{:s}_general".format(layer_def["pg_layer_name"]),
                      "exception_table": "v14_{:s}_exception".format(layer_def["pg_layer_name"]),
                      "error_table": "v14_{:s}_error".format(layer_def["pg_layer_name"])}

        # Create table of general items.
        sql = ("CREATE TABLE {general_table} AS"
               " WITH"
               "  inside_ua AS ("
               "   SELECT * FROM {layer_name} WHERE ua IS NOT NULL),"
               "  outside_ua AS ("
               "   SELECT * FROM {layer_name} WHERE ua IS NULL),"
               "  same_neighbour AS ("
               "   SELECT DISTINCT ta.{fid_name} AS {fid_name}"
               "   FROM outside_ua AS ta, outside_ua AS tb"
               "   WHERE"
               "    ta.{fid_name} <> tb.{fid_name}"
               "    AND ta.{code_column_name} = tb.{code_column_name}"
               "    AND ta.wkb_geometry && tb.wkb_geometry"
               "    AND ST_Dimension(ST_Intersection(ta.wkb_geometry, tb.wkb_geometry)) >= 1)"
               # All features inside Urban Atlas Core Region.
               " SELECT {fid_name}"
               " FROM inside_ua"
               # All features outside Urban Atlas Core Region not having neighbour with the same code.
               " UNION"
               " SELECT {fid_name}"
               " FROM outside_ua"
               " WHERE {fid_name} NOT IN (SELECT {fid_name} FROM same_neighbour);")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Create table of exception items.
        sql = ("CREATE TABLE {exception_table} AS"
               " WITH"
               "  layer AS ("
               "   SELECT *"
               "   FROM {layer_name}"
               "   WHERE"
               "    {fid_name} NOT IN (SELECT {fid_name} FROM {general_table}))"
               " SELECT {fid_name}"
               " FROM layer")
        if len(params["exception_comments"]) > 0:
            sql += (" WHERE comment IN %(exception_comments)s")
        else:
            sql += (" WHERE FALSE")
        sql += ";"
        sql = sql.format(**sql_params)
        cursor.execute(sql, {"exception_comments": tuple(params["exception_comments"])})

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
