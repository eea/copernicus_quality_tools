#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from qc_tool.wps.helper import do_layers
from qc_tool.wps.helper import get_failed_items_message


SQL = "CREATE TABLE {:s} AS SELECT {:s} FROM {:s} WHERE ST_NumGeometries(wkb_geometry) > 1;"


def run_check(params, status):
    cursor = params["connection_manager"].get_connection().cursor()
    for layer_def in do_layers(params):
        error_table_name = "v8_{:s}_error".format(layer_def["pg_layer_name"])
        sql = SQL.format(error_table_name, layer_def["pg_fid_name"], layer_def["pg_layer_name"])
        cursor.execute(sql)
        if cursor.rowcount > 0:
            failed_items_message = get_failed_items_message(cursor, error_table_name, layer_def["pg_fid_name"])
            status.failed("Layer {:s} has multipart geometries in features with {:s}: {:s}."
                          .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], failed_items_message))
            status.add_error_table(error_table_name, layer_def["pg_layer_name"], layer_def["pg_fid_name"])
