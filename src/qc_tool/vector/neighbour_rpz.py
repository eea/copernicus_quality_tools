#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "There is no couple of neighbouring polygons having the same code, Riparian zones."
IS_SYSTEM = False


def run_check(params, status):
    from qc_tool.vector.helper import do_layers
    from qc_tool.vector.helper import get_failed_items_message

    cursor = params["connection_manager"].get_connection().cursor()

    for layer_def in do_layers(params):
        # Prepare clause for pairing features.
        # Every feature is identified by composite key including
        # * value of every code column;
        # * IS NULL value of initial_ua_column_name;
        pair_clause = " AND ".join("ta.{0:s} = tb.{0:s}".format(code_column_name)
                                   for code_column_name in params["code_column_names"])
        if params["initial_ua_column_name"] is not None:
            pair_clause = " AND ".join([pair_clause,
                                        "(ta.{0:s} IS NULL) = (tb.{0:s} IS NULL)".format(params["initial_ua_column_name"])])

        # Prepare parameters used in sql clauses.
        sql_params = {"fid_name": layer_def["pg_fid_name"],
                      "layer_name": layer_def["pg_layer_name"],
                      "final_ua_column_name": params["final_ua_column_name"],
                      "general_table": "s{:02d}_{:s}_general".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "exception_table": "s{:02d}_{:s}_exception".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "error_table": "s{:02d}_{:s}_error".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "pair_clause": pair_clause}

        # All features not having neighbour with the same key.
        # Only features outside ua region in the final year (having final_ua_column_name set to NULL) are taken into trial.
        # All features inside ua region in the final year are considered ok and they are completely excluded from the pairing.
        sql = ("CREATE TABLE {general_table} AS"
               " SELECT {fid_name}"
               " FROM {layer_name}"
               " WHERE"
               "  {fid_name} NOT IN"
               "   (SELECT DISTINCT unnest(ARRAY[ta.{fid_name}, tb.{fid_name}]) AS {fid_name}"
               "    FROM {layer_name} AS ta, {layer_name} AS tb"
               "    WHERE"
               "     ta.{final_ua_column_name} IS NULL"
               "     AND tb.{final_ua_column_name} IS NULL"
               "     AND {pair_clause}"
               "     AND ta.{fid_name} < tb.{fid_name}"
               "     AND ta.geom && tb.geom"
               "     AND ST_Dimension(ST_Intersection(ta.geom, tb.geom)) >= 1"
               "   );")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Create table of exception items.
        sql = ("CREATE TABLE {exception_table} AS"
               " SELECT {fid_name}"
               " FROM {layer_name}"
               " WHERE"
               "  {fid_name} NOT IN (SELECT {fid_name} FROM {general_table})")
        if len(params["exception_comments"]) > 0:
            sql_execute_params = {"exception_comments": tuple(params["exception_comments"])}
            sql += " AND comment IN %(exception_comments)s"
        else:
            sql_execute_params = {}
            sql += " AND FALSE"
        sql += ";"
        sql = sql.format(**sql_params)
        cursor.execute(sql, sql_execute_params)

        # Report exception items.
        items_message = get_failed_items_message(cursor, sql_params["exception_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.info("Layer {:s} has exception features with {:s}: {:s}."
                        .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["exception_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

        # Create table of error items.
        sql = ("CREATE TABLE {error_table} AS"
               " SELECT {fid_name}"
               " FROM {layer_name}"
               " WHERE"
               "  {fid_name} NOT IN (SELECT {fid_name} FROM {general_table})"
               "  AND {fid_name} NOT IN (SELECT {fid_name} FROM {exception_table});")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report error items.
        items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.failed("Layer {:s} has error features with {:s}: {:s}."
                          .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])
