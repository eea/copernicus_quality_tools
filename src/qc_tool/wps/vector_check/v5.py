#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from qc_tool.wps.helper import get_failed_ids_message
from qc_tool.wps.registry import register_check_function


SQL = "CREATE TABLE {0:s} AS SELECT {1:s} FROM {2:s} GROUP BY {1:s} HAVING count({1:s}) > 1;"


@register_check_function(__name__)
def run_check(params, status):
    cursor = params["connection_manager"].get_connection().cursor()
    for layer_name in params["db_layer_names"]:
        error_table_name = "{:s}_uniqueid_error".format(layer_name)
        sql = SQL.format(error_table_name, params["ident_colname"], layer_name)
        cursor.execute(sql)
        if cursor.rowcount == 0:
            cursor.execute("DROP TABLE {:s};".format(error_table_name))
        else:
            failed_ids_message = get_failed_ids_message(cursor, error_table_name, params["ident_colname"])
            failed_message = "The layer {:s} has non-unique identifiers: {:s}.".format(layer_name, failed_ids_message)
            status.add_message(failed_message)
            status.add_error_table(error_table_name)
