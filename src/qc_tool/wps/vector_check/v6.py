#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import re

from qc_tool.wps.helper import get_failed_items_message
from qc_tool.wps.registry import register_check_function


SQL = "CREATE TABLE {:s} AS SELECT {:s} FROM {:s} WHERE {:s} NOT IN (SELECT code FROM v6_code WHERE data_type=%s);"


@register_check_function(__name__)
def run_check(params, status):
    cursor = params["connection_manager"].get_connection().cursor()
    for layer_name in params["db_layer_names"]:
        if "code_regex" in params:
            mobj = re.search(params["code_regex"], layer_name)
            code = mobj.group(1)
            column_defs = params["code_to_column_defs"][code]
        else:
            column_defs = params["column_defs"]

        for column_name, value_set_name in column_defs:
            error_table_name = "{:s}_{:s}_validcodes_error".format(layer_name, column_name)
            sql = SQL.format(error_table_name, params["fid_column_name"], layer_name, column_name)
            cursor.execute(sql, (value_set_name,))
            if cursor.rowcount == 0:
                cursor.execute("DROP TABLE {:s};".format(error_table_name))
            else:
                failed_items_message = get_failed_items_message(cursor, error_table_name, params["fid_column_name"])
                failed_message = "The layer {:s} has column {:s} with invalid codes in rows: {:s}.".format(layer_name, column_name, failed_items_message)
                status.add_message(failed_message)
                status.add_error_table(error_table_name)
