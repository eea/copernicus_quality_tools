#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import re


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
                      "area_m2": params["area_m2"],
                      "code_column_name": params["code_column_name"],
                      "error_table": "s{:02d}_{:s}_error".format(params["step_nr"], layer_def["pg_layer_name"])}

        # Create error item query.
        sql = ("CREATE TABLE {error_table} AS"
               " SELECT {fid_name}"
               " FROM {exclude_clause}"
               " WHERE {area_column_name} > {area_m2};")

        # Add exclude clause to error table query.
        exclude_codes = params.get("exclude_codes", [])
        if len(exclude_codes) > 0:
            exclude_clause = ",".join(["'{0}'".format(exclude_code) for exclude_code in exclude_codes])
            exclude_clause = ("(SELECT {fid_name}, {area_column_name} FROM {layer_name}"
                              " WHERE {code_column_name} NOT IN (" + exclude_clause + ")) c")
            exclude_clause = exclude_clause.format(**sql_params)
        else:
            exclude_clause = layer_def["pg_layer_name"]
        sql_params.update({"exclude_clause": exclude_clause})

        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report error items.
        items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.failed("Layer {:s} has error features with {:s}: {:s}."
                          .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])
