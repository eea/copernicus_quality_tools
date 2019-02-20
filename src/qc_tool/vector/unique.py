#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from qc_tool.vector.helper import do_layers
from qc_tool.vector.helper import get_failed_items_message


DESCRIPTION = "Features have unique values in specific attributes."
IS_SYSTEM = False

SQL = ("CREATE TABLE {0:s} AS (SELECT {1:s} FROM {3:s} WHERE {2:s} IN ("
       "SELECT {2:s} FROM {3:s} GROUP BY {2:s} HAVING count({2:s}) > 1));")


def run_check(params, status):
    cursor = params["connection_manager"].get_connection().cursor()
    for layer_def in do_layers(params):
        for unique_key in params["unique_keys"]:
            error_table_name = "v5_{:s}_{:s}_error".format(layer_def["pg_layer_name"], unique_key)
            sql = SQL.format(error_table_name,
                             layer_def["pg_fid_name"],
                             unique_key,
                             layer_def["pg_layer_name"])
            cursor.execute(sql)
            if cursor.rowcount > 0:
                failed_items_message = get_failed_items_message(cursor, error_table_name, layer_def["pg_fid_name"])
                status.failed("The column {:s}.{:s} has non-unique values in features with {:s}: {:s}."
                              .format(layer_def["pg_layer_name"], unique_key, layer_def["fid_display_name"], failed_items_message))
                status.add_error_table(error_table_name, layer_def["pg_layer_name"], layer_def["pg_fid_name"])
