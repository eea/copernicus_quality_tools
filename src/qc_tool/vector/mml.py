#!/usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Minimum mapping length."
IS_SYSTEM = False


def run_check(params, status):
    from qc_tool.vector.helper import do_layers
    from qc_tool.vector.helper import get_failed_items_message

    cursor = params["connection_manager"].get_connection().cursor()

    for layer_def in do_layers(params):
        # Prepare parameters used in sql clauses.
        sql_params = {"fid_name": layer_def["pg_fid_name"],
                      "layer_name": layer_def["pg_layer_name"],
                      "warning_table": "s{:02d}_{:s}_warning".format(params["step_nr"], layer_def["pg_layer_name"])}
        sql_execute_params = {"mml": params["mml"]}
        if params["code_column_name"] is None:
            sql_params["filter_clause"] = "TRUE"
        else:
            sql_params["code_column_name"] = params["code_column_name"]
            sql_params["filter_clause"] = "{code_column_name} = %(filter_code)s".format(**sql_params)
            sql_execute_params["filter_code"] = params["filter_code"]

        # Create table of warning items.
        sql = ("CREATE TABLE {warning_table} AS"
               " SELECT {fid_name}"
               " FROM {layer_name}"
               " WHERE"
               "  {filter_clause}"
               "  AND ST_Length(ST_ApproximateMedialAxis(geom)) < %(mml)s;")
        sql = sql.format(**sql_params)
        cursor.execute(sql, sql_execute_params)

        # Report warning features.
        items_message = get_failed_items_message(cursor, sql_params["warning_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.info("Layer {:s} has warning features with {:s}: {:s}."
                        .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["warning_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])
