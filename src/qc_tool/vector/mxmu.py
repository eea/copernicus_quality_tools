#!/usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Maximum mapping unit."
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
                      "error_where": params["error_where"],
                      "error_table": "s{:02d}_{:s}_error".format(params["step_nr"], layer_def["pg_layer_name"])}

        # Create table of error items.
        sql = ("CREATE TABLE {error_table} AS\n"
               "SELECT {fid_name}\n"
               "FROM {layer_name} AS layer\n"
               "WHERE\n"
               " ({error_where})\n"
               " AND {area_column_name} > %(mxmu)s;")
        sql = sql.format(**sql_params)
        cursor.execute(sql, {"mxmu": params["mxmu"]})

        # Report error items.
        items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.failed("Layer {:s} has error features with {:s}: {:s}."
                          .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])
