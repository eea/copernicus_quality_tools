#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import re

from qc_tool.wps.helper import do_layers
from qc_tool.wps.helper import get_failed_items_message


DESCRIPTION = "There is no couple of neighbouring polygons having the same code."
IS_SYSTEM = False


def run_check(params, status):
    cursor = params["connection_manager"].get_connection().cursor()

    for layer_def in do_layers(params):
        # Prepare clause excluding features with specific codes.
        exclude_clause = " AND ".join("{0:s} NOT LIKE '{1:s}'".format(code_column_name, exclude_code)
                                      for code_column_name in params["code_column_names"]
                                      for exclude_code in params.get("exclude_codes", []))
        if len(exclude_clause) > 0:
            exclude_clause = " WHERE " + exclude_clause

        # Prepare clause for pairing features.
        pair_clause = " AND ".join("ta.{0:s} = tb.{0:s}".format(code_column_name)
                                   for code_column_name in params["code_column_names"])
        if len(pair_clause) > 0:
            pair_clause = " AND " + pair_clause

        # Prepare parameters for sql query.
        sql_params = {"fid_name": layer_def["pg_fid_name"],
                      "layer_name": layer_def["pg_layer_name"],
                      "error_table": "v14_{:s}_error".format(layer_def["pg_layer_name"]),
                      "pair_clause": pair_clause,
                      "exclude_clause": exclude_clause}

        # Create table of error items.
        sql = ("CREATE TABLE {error_table} AS"
               " WITH"
               "  layer AS ("
               "   SELECT *"
               "   FROM {layer_name}"
               "   {exclude_clause})"
               " SELECT DISTINCT ta.{fid_name} AS {fid_name}"
               " FROM layer ta, layer tb"
               " WHERE"
               "  ta.{fid_name} <> tb.{fid_name}"
               "  {pair_clause}"
               "  AND ta.wkb_geometry && tb.wkb_geometry"
               "  AND ST_Dimension(ST_Intersection(ta.wkb_geometry, tb.wkb_geometry)) >= 1;")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report error items.
        items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.failed("Layer {:s} has error features with {:s}: {:s}."
                          .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])
