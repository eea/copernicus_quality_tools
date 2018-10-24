#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from qc_tool.wps.helper import do_layers
from qc_tool.wps.helper import dump_failed_items
from qc_tool.wps.helper import get_failed_items_message
from qc_tool.wps.registry import register_check_function

SQL = ("CREATE TABLE {0:s} AS (SELECT {1:s} FROM {3:s} WHERE {2:s} IN ("
       "SELECT {2:s} FROM {3:s} GROUP BY {2:s} HAVING count({2:s}) > 1));")

@register_check_function(__name__)
def run_check(params, status):
    cursor = params["connection_manager"].get_connection().cursor()
    for layer_def in do_layers(params):
        for unique_key in params["unique_keys"]:
            error_table_name = "{:s}_{:s}_uniqueid_error".format(layer_def["pg_layer_name"], unique_key)

            sql = SQL.format(error_table_name,
                             layer_def["pg_fid_name"],
                             unique_key,
                             layer_def["pg_layer_name"]
                             )
            cursor.execute(sql)
            if cursor.rowcount == 0:
                cursor.execute("DROP TABLE {:s};".format(error_table_name))
            else:
                failed_items_message = get_failed_items_message(cursor, error_table_name, layer_def["pg_fid_name"])
                failed_message = "The column {:s}.{:s} has non-unique values in rows: {:s}.".format(
                    layer_def["pg_layer_name"], unique_key, failed_items_message)
                status.add_message(failed_message)
                report_filename = dump_failed_items(params["connection_manager"],
                                                   error_table_name,
                                                   layer_def["pg_fid_name"],
                                                   layer_def["pg_layer_name"],
                                                   params["output_dir"])
                status.add_attachment(report_filename)
                status.add_error_table(error_table_name)
