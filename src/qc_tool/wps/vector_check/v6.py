#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from qc_tool.common import FAILED_ITEMS_LIMIT
from qc_tool.wps.helper import shorten_failed_items_message
from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    cursor = params["connection_manager"].get_connection().cursor()
    for layer_name in params["db_layer_names"]:
        error_table_name = "{:s}_validcodes_error".format(layer_name)
        cursor.execute("SELECT __V6_ValidCodes(%s, %s);", (layer_name, params["product_code"]))
        cursor.execute("SELECT DISTINCT {0:s} FROM {1:s} ORDER BY {0:s};".format(params["ident_colname"], error_table_name))
        if cursor.rowcount == 0:
            cursor.execute("DROP TABLE {:s};".format(error_table_name))
        else:
            failed_ids = [row[0] for row in cursor.fetchmany(FAILED_ITEMS_LIMIT)]
            failed_ids_message = shorten_failed_items_message(failed_ids, cursor.rowcount)
            failed_message = "The layer {:s} has invalid code in rows: {:s}.".format(layer_name, failed_ids_message)
            status.add_message(failed_message)
            status.add_error_table(error_table_name)
