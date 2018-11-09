#!/bin/env python3
# -*- coding: utf-8 -*-


import re

from qc_tool.wps.helper import do_layers
from qc_tool.wps.helper import get_failed_items_message
from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    cursor = params["connection_manager"].get_connection().cursor()

    for layer_def in do_layers(params):
        # Prepare parameters used in sql clauses.
        sql_params = {"fid_name": layer_def["pg_fid_name"],
                      "layer_name": layer_def["pg_layer_name"],
                      "area_column_name": params["area_column_name"],
                      "code_column_name": params["code_column_name"],
                      "general_table": "v11_{:s}_general".format(layer_def["pg_layer_name"]),
                      "exception_table": "v11_{:s}_exception".format(layer_def["pg_layer_name"]),
                      "warning_table": "v11_{:s}_warning".format(layer_def["pg_layer_name"]),
                      "error_table": "v11_{:s}_error".format(layer_def["pg_layer_name"])}

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
        sql = ("CREATE TABLE {exception_table} AS"
               " WITH"
               "  boundary AS ("
               "   SELECT ST_Boundary(ST_Union(wkb_geometry)) AS geom"
               "   FROM {layer_name}),"
               "  layer AS ("
               "   SELECT *"
               "   FROM {layer_name}"
               "   WHERE"
               "    {fid_name} NOT IN (SELECT {fid_name} FROM {general_table}))"
               # Items touching boundary.
               " SELECT layer.{fid_name}"
               " FROM layer, boundary"
               " WHERE"
               "  {area_column_name} >= 100"
               "  AND ST_Dimension(ST_Intersection(layer.wkb_geometry, boundary.geom)) >= 1"
               # Items touching cloud.
               " UNION"
               " SELECT layer.{fid_name}"
               " FROM layer, {layer_name} cloud"
               " WHERE"
               "  (layer.{code_column_name} NOT LIKE '9%' AND cloud.{code_column_name} LIKE '9%')"
               "  AND ST_Dimension(ST_Intersection(layer.wkb_geometry, cloud.wkb_geometry)) >= 1;")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report exception items.
        items_message = get_failed_items_message(cursor, sql_params["exception_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            message = "The layer {:s} has exception features: {:s}.".format(layer_def["pg_layer_name"], items_message)
            status.add_message(message, failed=False)
            status.add_error_table(sql_params["exception_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

        # Create table of warning items.
        sql = ("CREATE TABLE {warning_table} AS"
               " WITH"
               "  layer AS ("
               "   SELECT *"
               "   FROM {layer_name}"
               "   WHERE"
               "    {fid_name} NOT IN (SELECT {fid_name} FROM {general_table})"
               "    AND {fid_name} NOT IN (SELECT {fid_name} FROM {exception_table}))"
               " SELECT DISTINCT layer.{fid_name}"
               " FROM layer, {layer_name} road"
               " WHERE"
               "  layer.{area_column_name} >= 500"
               "  AND (layer.{code_column_name} NOT LIKE '122%' AND road.{code_column_name} LIKE '122%')"
               "  AND ST_Dimension(ST_Intersection(layer.wkb_geometry, road.wkb_geometry)) >= 1;")
        sql = sql.format(**sql_params)
        cursor.execute(sql)
            
        # Report warning items.
        items_message = get_failed_items_message(cursor, sql_params["warning_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            message = "The layer {:s} has warning features: {:s}.".format(layer_def["pg_layer_name"], items_message)
            status.add_message(message, failed=False)
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
            message = "The layer {:s} has error features: {:s}.".format(layer_def["pg_layer_name"], items_message)
            status.add_message(message)
            status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])
