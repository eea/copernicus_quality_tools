#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import re


DESCRIPTION = "Minimum mapping unit, Natura 2000."
IS_SYSTEM = False

CLUSTER_TABLE_NAME = "n2k_complex_change"


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
                      "code_column_name": params["final_code_column_name"],
                      "general_table": "s{:02d}_{:s}_general".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "cluster_table": CLUSTER_TABLE_NAME,
                      "exception_table": "s{:02d}_{:s}_exception".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "error_table": "s{:02d}_{:s}_error".format(params["step_nr"], layer_def["pg_layer_name"])}

        # Create table of general items.
        sql = ("CREATE TABLE {general_table} AS"
               " SELECT {fid_name}"
               " FROM {layer_name}"
               " WHERE {area_column_name} >= {area_ha};")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Create table of exception items.
        sql = ("CREATE TABLE {exception_table} AS"
               " WITH"
               "  margin AS ("
               "   SELECT ST_Boundary(ST_Union(wkb_geometry)) AS geom"
               "   FROM {layer_name}),"
               "  layer AS ("
               "   SELECT *"
               "   FROM {layer_name}"
               "   WHERE"
               "    {fid_name} NOT IN (SELECT {fid_name} FROM {general_table})),"
               "  randr AS ("
               "   SELECT *"
               "   FROM {layer_name}"
               "   WHERE"
               "    {code_column_name}::text SIMILAR TO '(121|122)%')"
               # Marginal features.
               " SELECT layer.{fid_name}"
               " FROM layer, margin"
               " WHERE"
               "  layer.{area_column_name} >= 0.1"
               "  AND ST_Dimension(ST_Intersection(layer.wkb_geometry, margin.geom)) >= 1"
               # Linear features.
               " UNION"
               " SELECT layer.{fid_name}"
               " FROM layer"
               " WHERE"
               "  layer.{area_column_name} >= 0.1"
               "  AND layer.{code_column_name}::text SIMILAR TO '(121|122|911|912)%'"
               # Urban features touching road or railway.
               " UNION"
               " SELECT layer.{fid_name}"
               " FROM layer, randr"
               " WHERE"
               "  layer.{area_column_name} >= 0.25"
               "  AND layer.{code_column_name}::text LIKE '1%'"
               "  AND layer.{code_column_name}::text NOT SIMILAR TO '(10|121|122)%'"
               "  AND ST_Dimension(ST_Intersection(layer.wkb_geometry, randr.wkb_geometry)) >= 1;")
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
                   "   HAVING sum({layer_name}.{area_column_name}) > 0.5);")
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
            status.failed("Layer {:s} has error features with {:s}: {:s}."
                          .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])