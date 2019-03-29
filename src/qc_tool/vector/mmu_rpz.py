#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import re


DESCRIPTION = "Minimum mapping unit, Riparian zones."
IS_SYSTEM = False


def run_check(params, status):
    from qc_tool.vector.helper import ComplexChangeCollector
    from qc_tool.vector.helper import do_layers
    from qc_tool.vector.helper import get_failed_items_message

    cursor = params["connection_manager"].get_connection().cursor()

    for layer_def in do_layers(params):
        # Prepare parameters used in sql clauses.
        sql_params = {"fid_name": layer_def["pg_fid_name"],
                      "layer_name": layer_def["pg_layer_name"],
                      "area_column_name": params["area_column_name"],
                      "area_ha": params["area_ha"],
                      "code_column_name": params["code_column_name"],
                      "general_table": "s{:02d}_{:s}_general".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "exception_table": "s{:02d}_{:s}_exception".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "error_table": "s{:02d}_{:s}_error".format(params["step_nr"], layer_def["pg_layer_name"])}

        # Create table of general items.
        sql = ("CREATE TABLE {general_table} AS"
               " SELECT {fid_name}"
               " FROM {layer_name}"
               " WHERE"
               "  ua IS NOT NULL"
               "  OR {area_column_name} >= {area_ha};")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Create table of exception items.
        # Marginal features.
        sql = ("CREATE TABLE {exception_table} AS"
               " SELECT layer.{fid_name}"
               " FROM"
               "  {layer_name} AS layer,"
               "  (SELECT ST_Boundary(ST_Union(wkb_geometry)) AS geom FROM {layer_name} WHERE ua IS NULL) AS margin"
               " WHERE"
               "  layer.{area_column_name} >= 0.2"
               "  AND layer.wkb_geometry && margin.geom"
               "  AND ST_Dimension(ST_Intersection(layer.wkb_geometry, margin.geom)) >= 1"
               "  AND layer.{fid_name} NOT IN (SELECT {fid_name} FROM {general_table});")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Urban features.
        if len(params["urban_feature_codes"]) > 0:
            sql_execute_params = {"urban_feature_codes": tuple(params["urban_feature_codes"])}
            sql = ("INSERT INTO {exception_table}"
                   " SELECT {fid_name}"
                   " FROM {layer_name}"
                   " WHERE"
                   "  {area_column_name} >= 0.25"
                   "  AND {code_column_name} IN %(urban_feature_codes)s"
                   "  AND {fid_name} NOT IN (SELECT {fid_name} FROM {general_table})"
                   "  AND {fid_name} NOT IN (SELECT {fid_name} FROM {exception_table});")
            sql = sql.format(**sql_params)
            cursor.execute(sql, sql_execute_params)

        # Linear features.
        if len(params["linear_feature_codes"]) > 0:
            sql_execute_params = {"linear_feature_codes": tuple(params["linear_feature_codes"])}
            sql = ("INSERT INTO {exception_table}"
                   " SELECT {fid_name}"
                   " FROM {layer_name}"
                   " WHERE"
                   "  {area_column_name} >= 0.1"
                   "  AND {code_column_name} IN %(linear_feature_codes)s"
                   "  AND {fid_name} NOT IN (SELECT {fid_name} FROM {general_table})"
                   "  AND {fid_name} NOT IN (SELECT {fid_name} FROM {exception_table});")
            sql = sql.format(**sql_params)
            cursor.execute(sql, sql_execute_params)

        # Features with specific comments.
        if len(params["exception_comments"]) > 0:
            sql_execute_params = {"exception_comments": tuple(params["exception_comments"])}
            sql = ("INSERT INTO {exception_table}"
                   " SELECT {fid_name}"
                   " FROM {layer_name}"
                   " WHERE"
                   "  comment IN %(exception_comments)s"
                   "  AND {fid_name} NOT IN (SELECT {fid_name} FROM {general_table})"
                   "  AND {fid_name} NOT IN (SELECT {fid_name} FROM {exception_table});")
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
