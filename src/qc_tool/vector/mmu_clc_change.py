#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import re

from qc_tool.wps.helper import ComplexChangeCollector
from qc_tool.wps.helper import do_layers
from qc_tool.wps.helper import get_failed_items_message


DESCRIPTION = "Minimum mapping unit, Corine Land Cover change layer."
IS_SYSTEM = False

CLUSTER_TABLE_NAME = "clc_complex_change"


def run_check(params, status):
    cursor = params["connection_manager"].get_connection().cursor()

    for layer_def in do_layers(params):
        # Prepare parameters used in sql clauses.
        sql_params = {"fid_name": layer_def["pg_fid_name"],
                      "layer_name": layer_def["pg_layer_name"],
                      "margin_layer_name": params["layer_defs"]["reference"]["pg_layer_name"],
                      "area_column_name": params["area_column_name"],
                      "area_m2": params["area_m2"],
                      "initial_code_column_name": params["initial_code_column_name"],
                      "final_code_column_name": params["final_code_column_name"],
                      "general_table": "v11_{:s}_general".format(layer_def["pg_layer_name"]),
                      "cluster_table": CLUSTER_TABLE_NAME,
                      "exception_table": "v11_{:s}_exception".format(layer_def["pg_layer_name"]),
                      "error_table": "v11_{:s}_error".format(layer_def["pg_layer_name"])}

        # Create table of general items.
        sql = ("CREATE TABLE {general_table} AS"
               " SELECT {fid_name}"
               " FROM {layer_name}"
               " WHERE"
               "  {area_column_name} >= {area_m2};")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Create table of exception items.
        sql = ("CREATE TABLE {exception_table} AS"
               " WITH"
               "  margin AS ("
               "   SELECT ST_Boundary(ST_Union(wkb_geometry)) AS geom"
               "   FROM {margin_layer_name}),"
               "  layer AS ("
               "   SELECT *"
               "   FROM {layer_name}"
               "   WHERE"
               "    {fid_name} NOT IN (SELECT {fid_name} FROM {general_table}))"
               # Marginal features.
               " SELECT layer.{fid_name}"
               " FROM layer, margin"
               " WHERE"
               "  ST_Dimension(ST_Intersection(layer.wkb_geometry, margin.geom)) >= 1;")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Add exceptions comming from complex change.
        # Do that once for initial code and once again for final code.
        for code_column_name in (params["initial_code_column_name"],
                                 params["final_code_column_name"]):

            # Find potential bad fids.
            sql = ("SELECT {fid_name}"
                   " FROM {layer_name}"
                   " WHERE"
                   "  {fid_name} NOT IN (SELECT {fid_name} FROM {general_table})"
                   "  AND {fid_name} NOT IN (SELECT {fid_name} FROM {exception_table});")
            sql = sql.format(**sql_params)
            cursor.execute(sql)
            bad_fids = [row[0] for row in cursor.fetchall()]

            # Build clusters from bad fids.
            ccc = ComplexChangeCollector(cursor,
                                         CLUSTER_TABLE_NAME,
                                         layer_def["pg_layer_name"],
                                         layer_def["pg_fid_name"],
                                         code_column_name)
            ccc.create_cluster_table()
            ccc.build_clusters(bad_fids)
            del ccc

            # Add good fids to exception.
            sql = ("INSERT INTO {exception_table}"
                   " SELECT fid"
                   " FROM {cluster_table}"
                   " WHERE "
                   "  fid NOT IN (SELECT {fid_name} FROM {general_table})"
                   "  AND fid NOT IN (SELECT {fid_name} FROM {exception_table})"
                   "  AND cluster_id IN ("
                   "   SELECT cluster_id"
                   "   FROM {cluster_table} INNER JOIN {layer_name} ON {cluster_table}.fid = {layer_name}.{fid_name}"
                   "   GROUP BY cluster_id"
                   "   HAVING sum({layer_name}.shape_area) >= 50000);")
            sql = sql.format(**sql_params)
            cursor.execute(sql)

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
            status.info("Layer {:s} has error features with {:s}: {:s}."
                        .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])
