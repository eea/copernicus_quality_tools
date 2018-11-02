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
        sql_params = {"boundary_layer_name": params["layer_defs"]["boundary"]["pg_layer_name"],
                      "fid_name": layer_def["pg_fid_name"],
                      "layer_name": layer_def["pg_layer_name"],
                      "area_column_name": params["area_column_name"],
                      "area_m2": params["area_m2"],
                      "boundary_items_table": "v11_{:s}_boundary_items".format(layer_def["pg_layer_name"]),
                      "general_table": "v11_{:s}_general".format(layer_def["pg_layer_name"]),
                      "exception_table": "v11_{:s}_exception".format(layer_def["pg_layer_name"]),
                      "error_table": "v11_{:s}_error".format(layer_def["pg_layer_name"])}

        # Create intermediate table of items touching boundary.
        sql = ("CREATE TABLE {boundary_items_table} AS"
               " SELECT DISTINCT layer.{fid_name}"
               " FROM {layer_name} layer, {boundary_layer_name} boundary"
               " WHERE ST_Dimension(ST_Intersection(layer.wkb_geometry, ST_Boundary(ST_Transform(boundary.wkb_geometry, ST_SRID(layer.wkb_geometry))))) >= 1;")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Create table of general items.
        sql = ("CREATE TABLE {general_table} AS"
               " SELECT {fid_name}"
               " FROM {layer_name}"
               " WHERE {area_column_name} >= {area_m2};")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Create table of exception items.
        sql = ("CREATE TABLE {exception_table} AS"
               " SELECT {fid_name}"
               " FROM {layer_name}"
               " WHERE"
               "  {fid_name} IN (SELECT {fid_name} FROM {boundary_items_table})"
               "  AND {fid_name} NOT IN (SELECT {fid_name} FROM {general_table});")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report exception items.
        items_message = get_failed_items_message(cursor, sql_params["exception_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            message = "The layer {:s} has exception features: {:s}.".format(layer_def["pg_layer_name"], items_message)
            status.add_message(message, failed=False)
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
            message = "The layer {:s} has error features: {:s}.".format(layer_def["pg_layer_name"], items_message)
            status.add_message(message)
            status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])
