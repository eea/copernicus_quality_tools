#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from qc_tool.wps.helper import get_failed_items_message
from qc_tool.wps.registry import register_check_function


SQL = "CREATE TABLE {:s} AS SELECT {:s} FROM {:s} WHERE ST_NumGeometries(wkb_geometry) > 1;"


@register_check_function(__name__)
def run_check(params, status):
    cursor = params["connection_manager"].get_connection().cursor()
    for layer_name in params["db_layer_names"]:
        error_table_name = "{:s}_multipartpolyg_error".format(layer_name)
        sql = SQL.format(error_table_name, params["fid_column_name"], layer_name)
        cursor.execute(sql)
        if cursor.rowcount == 0:
            cursor.execute("DROP TABLE {:s};".format(error_table_name))
        else:
            failed_items_message = get_failed_items_message(cursor, error_table_name, params["fid_column_name"])
            failed_message = "The layer {:s} has multipart geometries in rows: {:s}.".format(layer_name, failed_items_message)
            status.add_message(failed_message)
            status.add_error_table(error_table_name)
