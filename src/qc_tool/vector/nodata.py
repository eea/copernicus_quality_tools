#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "If a feature has nodata set, then all dependent attributes must have specific value."
IS_SYSTEM = False


def run_check(params, status):
    from qc_tool.vector.helper import do_layers
    from qc_tool.vector.helper import get_failed_items_message

    cursor = params["connection_manager"].get_connection().cursor()
    for layer_def in do_layers(params):
        for dep_column_name in params["dep_column_names"]:
            # Prepare parameters used in sql clauses.
            sql_params = {"fid_name": layer_def["pg_fid_name"],
                          "layer_name": layer_def["pg_layer_name"],
                          "nodata_column_name": params["nodata_column_name"],
                          "dep_column_name": dep_column_name,
                          "error_table": "s{:02d}_{:s}_{:s}_error".format(params["step_nr"],
                                                                          layer_def["pg_layer_name"],
                                                                          dep_column_name)}

            sql_execute_params = {}
            if params["nodata_value"] is None:
                sql_params["nodata_clause"] = "{nodata_column_name} IS NULL".format(**sql_params)
            else:
                sql_params["nodata_clause"] = "{nodata_column_name} = %(nodata_value)s".format(**sql_params)
                sql_execute_params["nodata_value"] = params["nodata_value"]
            if dep_column_name is None:
                sql_params["dep_clause"] = "{dep_column_name} IS NULL".format(**sql_params)
            else:
                sql_params["dep_clause"] = "{dep_column_name} = %(dep_value)s".format(**sql_params)
                sql_execute_params["dep_value"] = params["dep_value"]

            # Create table of error items.
            sql = ("CREATE TABLE {error_table} AS"
                   " SELECT {fid_name}"
                   " FROM {layer_name}"
                   " WHERE {nodata_clause} AND {dep_clause};")
            sql = sql.format(**sql_params)
            cursor.execute(sql, sql_execute_params)

            # Report error items.
            items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
            if items_message is not None:
                status.failed("Layer {:s} has column {:s} with invalid nodata code in features with {:s}: {:s}."
                              .format(layer_def["pg_layer_name"], layer_def["nodata_column_name"], layer_def["fid_display_name"], items_message))
                status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])
