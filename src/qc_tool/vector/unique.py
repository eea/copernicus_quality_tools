#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Features have unique values in specific attributes."
IS_SYSTEM = False


def run_check(params, status):
    from qc_tool.vector.helper import do_layers
    from qc_tool.vector.helper import get_failed_items_message

    cursor = params["connection_manager"].get_connection().cursor()
    for layer_def in do_layers(params):
        for unique_key in params["unique_keys"]:
            sql_params = {"fid_name": layer_def["pg_fid_name"],
                          "layer_name": layer_def["pg_layer_name"],
                          "unique_column_name": unique_key,
                          "error_table_name": "s{:02d}_{:s}_{:s}_error".format(params["step_nr"], layer_def["pg_layer_name"], unique_key)}
            sql = ("CREATE TABLE {error_table_name} AS\n"
                   "SELECT layer.{fid_name}\n"
                   "FROM\n"
                   " {layer_name} AS layer\n"
                   " INNER JOIN (SELECT {unique_column_name}\n"
                   "             FROM {layer_name}\n"
                   "             GROUP BY {unique_column_name}\n"
                   "             HAVING count({unique_column_name}) > 1) AS ut ON layer.{unique_column_name} = ut.{unique_column_name};")
            sql = sql.format(**sql_params)
            cursor.execute(sql)
            if cursor.rowcount > 0:
                failed_items_message = get_failed_items_message(cursor, sql_params["error_table_name"], layer_def["pg_fid_name"])
                status.failed("The column {:s}.{:s} has non-unique values in features with {:s}: {:s}."
                              .format(layer_def["pg_layer_name"], unique_key, layer_def["fid_display_name"], failed_items_message))
                status.add_error_table(sql_params["error_table_name"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])
