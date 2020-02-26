#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "There is no couple of neighbouring polygons having the same code."
IS_SYSTEM = False

TECHNICAL_CHANGE_FLAG = "T"


def run_check(params, status):
    from qc_tool.vector.helper import do_layers
    from qc_tool.vector.helper import get_failed_items_message

    cursor = params["connection_manager"].get_connection().cursor()
    for layer_def in do_layers(params):
        # Prepare clause excluding features with specific codes.
        exclude_clause = " AND ".join("{:s} NOT LIKE '{:s}'".format(code_column_name, exclude_code)
                                      for code_column_name in params["code_column_names"]
                                      for exclude_code in params.get("exclude_codes", []))
        if len(exclude_clause) == 0:
            exclude_clause = "TRUE"

        # Prepare clause for pairing features.
        if len(params["code_column_names"]) > 0:
            pair_clause = " AND ".join("ta.{0:s} = tb.{0:s}".format(code_column_name)
                                       for code_column_name in params["code_column_names"])
        else:
            pair_clause = "FALSE"

        # Prepare clause for technical change.
        if "chtype_column_name" in params:
            technical_clause = ("((ta.{0:s} = '{1:s}') IS TRUE OR (tb.{0:s} = '{1:s}') IS TRUE)"
                                .format(params["chtype_column_name"], TECHNICAL_CHANGE_FLAG))
        else:
            technical_clause = "FALSE"

        # Prepare parameters for sql query.
        sql_params = {"fid_name": layer_def["pg_fid_name"],
                      "layer_name": layer_def["pg_layer_name"],
                      "pair_table": "s{:02d}_{:s}_pairs".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "exception_table": "s{:02d}_{:s}_exception".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "error_table": "s{:02d}_{:s}_error".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "technical_clause": technical_clause,
                      "pair_clause": pair_clause,
                      "exclude_clause": exclude_clause}

        # Create temporary table of suspected pairs.
        sql = ("CREATE TABLE {pair_table} AS"
               " SELECT ARRAY[ta.{fid_name}, tb.{fid_name}] AS pair, {technical_clause} AS technical"
               " FROM"
               "  (SELECT * FROM {layer_name} WHERE {exclude_clause}) AS ta,"
               "  (SELECT * FROM {layer_name} WHERE {exclude_clause}) AS tb"
               " WHERE"
               "  ta.{fid_name} < tb.{fid_name}"
               "  AND {pair_clause}"
               "  AND ta.geom && tb.geom"
               "  AND ST_Dimension(ST_Intersection(ta.geom, tb.geom)) >= 1;")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Extract exception items.
        sql = ("CREATE TABLE {exception_table} AS"
               " SELECT DISTINCT unnest(pair) AS {fid_name}"
               " FROM {pair_table}"
               " WHERE technical;")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report exception items.
        items_message = get_failed_items_message(cursor, sql_params["exception_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.info("Layer {:s} has exception features with {:s}: {:s}."
                          .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["exception_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

        # Extract error items.
        sql = ("CREATE TABLE {error_table} AS"
               " SELECT DISTINCT unnest(pair) AS {fid_name}"
               " FROM {pair_table}"
               " WHERE NOT technical;")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report error items.
        items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.failed("Layer {:s} has error features with {:s}: {:s}."
                          .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])
