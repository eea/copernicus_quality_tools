#!/usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Linear and patchy features have appropriate compactness coefficient."
IS_SYSTEM = False


def run_check(params, status):
    """
    Check compactness of linear and patchy features.

    Features marked as linear must have compactness less then threshold.
    Features marked as patchy must have compactness greater then threshold.
    Features not marked as linear or patchy are not validated.

    Compactness is measured using Polsby-Popper method,
    see `Measuring District Compactness in PostGIS <https://www.azavea.com/blog/2016/07/11/measuring-district-compactness-postgis/>`__.
    """
    from qc_tool.vector.helper import do_layers
    from qc_tool.vector.helper import get_failed_items_message

    cursor = params["connection_manager"].get_connection().cursor()

    for layer_def in do_layers(params):
        # Prepare parameters used in sql clauses.
        sql_params = {"fid_name": layer_def["pg_fid_name"],
                      "layer_name": layer_def["pg_layer_name"],
                      "area_column_name": params["area_column_name"],
                      "code_column_name": params["code_column_name"],
                      "linear_error_table": "s{:02d}_{:s}_linear_error".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "patchy_error_table": "s{:02d}_{:s}_patchy_error".format(params["step_nr"], layer_def["pg_layer_name"])}
        sql_execute_params = {"threshold": params["threshold"],
                              "linear_code": params["linear_code"],
                              "patchy_code": params["patchy_code"]}

        # Create table of error items of linear features.
        sql = ("CREATE TABLE {linear_error_table} AS"
               " SELECT {fid_name}"
               " FROM {layer_name}"
               " WHERE"
               "  {code_column_name} = %(linear_code)s"
               "  AND 4 * pi() * {area_column_name} / power(ST_Perimeter(geom), 2) > %(threshold)s;")
        sql = sql.format(**sql_params)
        cursor.execute(sql, sql_execute_params)

        # Report error items of linear features
        items_message = get_failed_items_message(cursor, sql_params["linear_error_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.failed("Layer {:s} has error linear features with {:s}: {:s}."
                          .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["linear_error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

        # Create table of error items of patchy features.
        sql = ("CREATE TABLE {patchy_error_table} AS"
               " SELECT {fid_name}"
               " FROM {layer_name}"
               " WHERE"
               "  {code_column_name} = %(patchy_code)s"
               "  AND 4 * pi() * {area_column_name} / power(ST_Perimeter(geom), 2) <= %(threshold)s;")
        sql = sql.format(**sql_params)
        cursor.execute(sql, sql_execute_params)

        # Report error items of patchy features
        items_message = get_failed_items_message(cursor, sql_params["patchy_error_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.failed("Layer {:s} has error patchy features with {:s}: {:s}."
                          .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["patchy_error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])
