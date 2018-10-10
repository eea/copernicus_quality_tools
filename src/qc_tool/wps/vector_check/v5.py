#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from qc_tool.wps.helper import get_failed_items_message
from qc_tool.wps.registry import register_check_function


SQL = "CREATE TABLE {0:s} AS SELECT {1:s} FROM {2:s} GROUP BY {1:s} HAVING count({1:s}) > 1;"


@register_check_function(__name__)
def run_check(params, status):
    cursor = params["connection_manager"].get_connection().cursor()
    for layer_def in params["layer_defs"].values():
        for unique_key in params["unique_keys"]:
            error_table_name = "{:s}_{:s}_uniqueid_error".format(layer_def["pg_layer_name"], unique_key)
            sql = SQL.format(error_table_name, unique_key, layer_def["pg_layer_name"])
            cursor.execute(sql)
            if cursor.rowcount == 0:
                cursor.execute("DROP TABLE {:s};".format(error_table_name))
            else:
                failed_items_message = get_failed_items_message(cursor, error_table_name, unique_key)
                failed_message = "The column {:s}.{:s} has non-unique values: {:s}.".format(layer_def["pg_layer_name"], unique_key, failed_items_message)
                status.add_message(failed_message)
                status.add_error_table(error_table_name)
