#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Features have distinct code in initial and final year"
IS_SYSTEM = False


def run_check(params, status):
    from qc_tool.vector.helper import do_layers
    from qc_tool.vector.helper import get_failed_items_message

    cursor = params["connection_manager"].get_connection().cursor()
    for layer_def in do_layers(params):

        # Features matching exclude_clause are not reported as errors.
        if "chtype_column_name" and "chtype_exception_value" in params:
            exception_params = {"chtype_column_name": params["chtype_column_name"],
                                "chtype_exception_value": params["chtype_exception_value"]}
            exclude_clause = "AND ({chtype_column_name} IS NULL OR {chtype_column_name} != '{chtype_exception_value}')"
            exclude_clause = exclude_clause.format(**exception_params)
            exception_clause = "AND ({chtype_column_name} IS NOT NULL AND {chtype_column_name} = '{chtype_exception_value}')"
            exception_clause = exception_clause.format(**exception_params)
        else:
            exclude_clause = ""
            exception_clause = ""

        # Prepare parameters used in sql clauses.
        sql_params = {"fid_name": layer_def["pg_fid_name"],
                      "layer_name": layer_def["pg_layer_name"],
                      "initial_code_column_name": params["initial_code_column_name"],
                      "final_code_column_name": params["final_code_column_name"],
                      "exclude_clause": exclude_clause,
                      "exception_clause": exception_clause,
                      "chtype_column_name": params["chtype_column_name"],
                      "chtype_exception_value": params["chtype_exception_value"],
                      "error_table": "s{:02d}_{:s}_error".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "exception_table": "s{:02d}_{:s}_exception".format(params["step_nr"],
                                                                         layer_def["pg_layer_name"])}

        # Create table of exception items (if applicable).
        if "chtype_column_name" and "chtype_exception_value" in params:

            sql = ("CREATE TABLE {exception_table} AS"
                   " SELECT {fid_name}"
                   " FROM {layer_name}"
                   " WHERE"
                   "  ({initial_code_column_name} = {final_code_column_name})"
                   "  {exception_clause};")
            sql = sql.format(**sql_params)
            cursor.execute(sql)

            items_message = get_failed_items_message(cursor, sql_params["exception_table"], layer_def["pg_fid_name"])
            if items_message is not None:
                status.info("Layer {:s} has exception features with {:s}: {:s}."
                            .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
                status.add_error_table(sql_params["exception_table"], layer_def["pg_layer_name"],
                                       layer_def["pg_fid_name"])

        # Create table of error items.
        sql = ("CREATE TABLE {error_table} AS"
               " SELECT {fid_name}"
               " FROM {layer_name}"
               " WHERE"
               "  ({initial_code_column_name} = {final_code_column_name})"
               "  {exclude_clause};")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report error items.
        items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.failed("Layer {:s} has code in {:s} and {:s} columns in features with {:s}: {:s}."
                          .format(params["initial_code_column_name"],
                                  params["final_code_column_name"],
                                  layer_def["pg_layer_name"],
                                  layer_def["fid_display_name"],
                                  items_message))
            status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])
