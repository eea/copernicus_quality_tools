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
                      "initial_code_column_name": params["initial_code_column_name"],
                      "final_code_column_name": params["final_code_column_name"],
                      "boundary_items_table": "v11_{:s}_boundary_items".format(layer_def["pg_layer_name"]),
                      "complex_items_table": "v11_{:s}_complex_items".format(layer_def["pg_layer_name"]),
                      "exception_table": "v11_{:s}_exception".format(layer_def["pg_layer_name"]),
                      "error_table": "v11_{:s}_error".format(layer_def["pg_layer_name"])}

        # Create intermediate table of boundary items.
        sql = ("CREATE TABLE {boundary_items_table} AS"
               " SELECT DISTINCT layer.{fid_name}"
               " FROM {layer_name} layer, {boundary_layer_name} b"
               " WHERE ST_Dimension(ST_Intersection(layer.wkb_geometry, ST_Boundary(ST_Transform(b.wkb_geometry, ST_SRID(layer.wkb_geometry))))) >= 1;")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Create intermediate table of complex changes items.
        sql = ("CREATE TABLE {complex_items_table} AS"
               " SELECT DISTINCT ch1.{fid_name}"
               " FROM {layer_name} ch1, {layer_name} ch2"
               " WHERE"
               "  ch1.{fid_name} <> ch2.{fid_name}"
               "  AND (ch1.{initial_code_column_name} = ch2.{initial_code_column_name} OR ch1.{final_code_column_name} = ch2.{final_code_column_name})"
               "  AND ch1.{area_column_name} + ch2.{area_column_name} > {area_m2}"
               "  AND ST_Dimension(ST_Intersection(ch1.wkb_geometry, ch2.wkb_geometry)) >= 1;")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Create table of exception items.
        sql = ("CREATE TABLE {exception_table} AS"
               " SELECT {fid_name}"
               " FROM {layer_name}"
               " WHERE"
               "  NOT {area_column_name} >= {area_m2}"
               "  AND ({fid_name} IN (SELECT {fid_name} FROM {boundary_items_table})"
               "       OR {fid_name} IN (SELECT {fid_name} FROM {complex_items_table}));")
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
               "  NOT {area_column_name} >= {area_m2}"
               "  AND {fid_name} NOT IN (SELECT {fid_name} FROM {exception_table});")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report error items.
        items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            message = "The layer {:s} has error features: {:s}.".format(layer_def["pg_layer_name"], items_message)
            status.add_message(message)
            status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])