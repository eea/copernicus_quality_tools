#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import re

from qc_tool.wps.helper import do_layers
from qc_tool.wps.helper import get_failed_items_message
from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    cursor = params["connection_manager"].get_connection().cursor()
    for layer_def in do_layers(params):
        for column_name, allowed_codes in params["column_defs"]:

            # Prepare clause excluding features with non-null value of specific column.
            if "exclude_column_name" in params:
                exclude_clause = " WHERE {:s} IS NULL".format(params["exclude_column_name"])
            else:
                exclude_clause = ""

            # Prepare parameters used in sql clauses.
            sql_params = {"fid_name": layer_def["pg_fid_name"],
                          "layer_name": layer_def["pg_layer_name"],
                          "column_name": column_name,
                          "exclude_clause": exclude_clause,
                          "error_table": "v6_{:s}_{:s}_error".format(layer_def["pg_layer_name"], column_name)}

            # Create table of error items.
            # Create table of error items.
            sql = ("  CREATE TABLE {error_table} AS"
                   "   WITH"
                   "   layer AS ("
                   "    SELECT *"
                   "    FROM {layer_name}"
                   "    {exclude_clause})"
                   "  SELECT {fid_name}"
                   "  FROM layer"
                   "  WHERE layer.{column_name} IS NULL"
                   "   OR layer.{column_name} NOT IN %s")
            sql = sql.format(**sql_params)

            cursor.execute(sql, [tuple(allowed_codes)])

            # Report error items.
            items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
            if items_message is not None:
                status.failed("Layer {:s} has column {:s} with invalid codes in features with {:s}: {:s}."
                              .format(layer_def["pg_layer_name"], column_name, layer_def["fid_display_name"], items_message))
                status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])
