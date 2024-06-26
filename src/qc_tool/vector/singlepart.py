#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "All geometries are singlepart."
IS_SYSTEM = False

SQL = "CREATE TABLE {:s} AS SELECT {:s} FROM {:s} WHERE ST_NumGeometries(geom) > 1;"


def run_check(params, status):
    from qc_tool.vector.helper import do_layers
    from qc_tool.vector.helper import get_failed_items_message

    # Check if the current delivery is excluded from vector checks
    if "skip_vector_checks" in params:
        if params["skip_vector_checks"]:
            status.info("The delivery has been excluded from vector.singlepart check because the vector data source does not contain a single object of interest.")
            return

    cursor = params["connection_manager"].get_connection().cursor()
    for layer_def in do_layers(params):
        error_table_name = "s{:02d}_{:s}_error".format(params["step_nr"], layer_def["pg_layer_name"])
        sql = SQL.format(error_table_name, layer_def["pg_fid_name"], layer_def["pg_layer_name"])
        cursor.execute(sql)
        if cursor.rowcount > 0:
            failed_items_message = get_failed_items_message(cursor, error_table_name, layer_def["pg_fid_name"])
            status.aborted("Layer {:s} has multipart geometries in features with {:s}: {:s}."
                          .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], failed_items_message))
            status.add_error_table(error_table_name, layer_def["pg_layer_name"], layer_def["pg_fid_name"])
