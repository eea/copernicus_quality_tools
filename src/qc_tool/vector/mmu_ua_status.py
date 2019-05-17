#!/usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Minimum mapping unit, Urban Atlas status layer."
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
                      "code_column_name": params["code_column_name"],
                      "general_table": "s{:02d}_{:s}_general".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "exception_table": "s{:02d}_{:s}_exception".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "warning_table": "s{:02d}_{:s}_warning".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "error_table": "s{:02d}_{:s}_error".format(params["step_nr"], layer_def["pg_layer_name"])}

        # Create table of general items.
        sql = ("CREATE TABLE {general_table} AS"
               " SELECT {fid_name}"
               " FROM {layer_name}"
               " WHERE"
               "  {code_column_name} LIKE '122%'"
               "  OR ({code_column_name} LIKE '1%' AND {area_column_name} >= 2500)"
               "  OR ({code_column_name} SIMILAR TO '[2-5]%' AND {area_column_name} >= 10000)"
               "  OR {code_column_name} LIKE '9%';")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Create table of exception items.
        # Items touching boundary.
        sql = ("CREATE TABLE {exception_table} AS"
               " SELECT layer.{fid_name}"
               " FROM"
               "  {layer_name} AS layer,"
               "  (SELECT ST_Boundary(ST_Union(geom)) AS geom FROM {layer_name}) AS boundary"
               " WHERE"
               "  {area_column_name} >= 100"
               "  AND layer.geom && boundary.geom"
               "  AND ST_Dimension(ST_Intersection(layer.geom, boundary.geom)) >= 1"
               "  AND layer.{fid_name} NOT IN (SELECT {fid_name} FROM {general_table});")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Items touching cloud.
        sql = ("INSERT INTO {exception_table}"
               " SELECT layer.{fid_name}"
               " FROM"
               "  {layer_name} AS layer,"
               "  {layer_name} AS cloud"
               " WHERE"
               "  (layer.{code_column_name} NOT LIKE '9%' AND cloud.{code_column_name} LIKE '9%')"
               "  AND layer.geom && cloud.geom"
               "  AND ST_Dimension(ST_Intersection(layer.geom, cloud.geom)) >= 1"
               "  AND layer.{fid_name} NOT IN (SELECT {fid_name} FROM {general_table})"
               "  AND layer.{fid_name} NOT IN (SELECT {fid_name} FROM {exception_table});")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report exception items.
        items_message = get_failed_items_message(cursor, sql_params["exception_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.info("Layer {:s} has exception features with {:s}: {:s}."
                        .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["exception_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

        # Create table of warning items.
        sql = ("CREATE TABLE {warning_table} AS"
               " SELECT DISTINCT layer.{fid_name}"
               " FROM"
               "  {layer_name} AS layer,"
               "  {layer_name} AS road"
               " WHERE"
               "  layer.{area_column_name} >= 500"
               "  AND (layer.{code_column_name} NOT LIKE '122%' AND road.{code_column_name} LIKE '122%')"
               "  AND layer.geom && road.geom"
               "  AND ST_Dimension(ST_Intersection(layer.geom, road.geom)) >= 1"
               "  AND layer.{fid_name} NOT IN (SELECT {fid_name} FROM {general_table})"
               "  AND layer.{fid_name} NOT IN (SELECT {fid_name} FROM {exception_table});")
        sql = sql.format(**sql_params)
        cursor.execute(sql)
            
        # Report warning items.
        items_message = get_failed_items_message(cursor, sql_params["warning_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.info("Layer {:s} has warning features with {:s}: {:s}."
                        .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["warning_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

        # Create table of error items.
        sql = ("CREATE TABLE {error_table} AS"
               " SELECT {fid_name}"
               " FROM {layer_name}"
               " WHERE"
               "  {fid_name} NOT IN (SELECT {fid_name} FROM {general_table})"
               "  AND {fid_name} NOT IN (SELECT {fid_name} FROM {exception_table})"
               "  AND {fid_name} NOT IN (SELECT {fid_name} FROM {warning_table});")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report error items.
        items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.failed("Layer {:s} has error features with {:s}: {:s}."
                          .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])
