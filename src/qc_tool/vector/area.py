#!/usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Area attribute has correct values."
IS_SYSTEM = False


def run_check(params, status):
    from qc_tool.vector.helper import do_layers
    from qc_tool.vector.helper import get_failed_items_message

    cursor = params["connection_manager"].get_connection().cursor()

    for layer_def in do_layers(params):
        # Prepare parameters used in sql clauses.
        sql_params = {"fid_name": layer_def["pg_fid_name"],
                      "layer_name": layer_def["pg_layer_name"],
                      "area_column_name": params["area_column_name"],
                      "error_table": "s{:02d}_{:s}_error".format(params["step_nr"], layer_def["pg_layer_name"])}
        sql_execute_params = {"unit": params["unit"],
                              "tolerance": params["tolerance"]}

        # Create table of error items.
        sql = ("CREATE TABLE {error_table} AS"
               " SELECT {fid_name}"
               " FROM {layer_name}"
               " WHERE abs({area_column_name} - ST_Area(geom) / %(unit)s) > %(tolerance)s;")
        sql = sql.format(**sql_params)
        cursor.execute(sql, sql_execute_params)

        # Report error items.
        items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.failed("Layer {:s} has error features with {:s}: {:s}."
                          .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])
