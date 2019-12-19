#!/usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "There is no gap in the set of AOIs."
IS_SYSTEM = False


def run_check(params, status):
    from qc_tool.vector.helper import do_layers

    cursor = params["connection_manager"].get_connection().cursor()

    if "boundary" not in params["layer_defs"]:
        status.info("Check cancelled due to boundary not being available.")
        return

    tolerance = params.get("tolerance", 0)
    if tolerance is None:
        tolerance = 0

    for layer_def in do_layers(params):
        # Prepare parameters used in sql clauses.
        sql_params = {"layer_name": layer_def["pg_layer_name"],
                      "boundary_name": params["layer_defs"]["boundary"]["pg_layer_name"],
                      "boundary_unit_column_name": params["boundary_unit_column_name"],
                      "tolerance": tolerance,
                      "boundary_union_table": "s{:02d}_{:s}_boundary_union_table".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "layer_union_table": "s{:02d}_{:s}_layer_union_table".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "layer_union_table1": "s{:02d}_{:s}_layer_union_table1".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "layer_union_table2": "s{:02d}_{:s}_layer_union_table2".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "gap_suspect_table": "s{:02d}_{:s}_gap_suspect".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "gap_warning_table": "s{:02d}_{:s}_gap_warning".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "unit_warning_table": "s{:02d}_{:s}_unit_warning".format(params["step_nr"], layer_def["pg_layer_name"])}

        # Create boundary union table.
        sql = ("CREATE TABLE {boundary_union_table} AS"
               " (SELECT"
               " {boundary_unit_column_name},"
               " ST_Union(geom) AS geom"
               " FROM {boundary_name}"
               " WHERE {boundary_unit_column_name} IN (SELECT DISTINCT {boundary_unit_column_name} FROM {layer_name})"
               " GROUP BY {boundary_unit_column_name})")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Create layer union table of small polygons.
        sql = ("CREATE TABLE {layer_union_table1} AS"
               "  (SELECT"
               "    {boundary_unit_column_name},"
               "    ST_Buffer(ST_Collect(geom), 0) AS geom"
               "   FROM {layer_name}"
               "   WHERE ST_NPoints(geom) < 500000"
               "   GROUP BY {boundary_unit_column_name}"
               "  )"
               )
        sql = sql.format(**sql_params)
        cursor.execute(sql)
        status.info("Created union table of small polygons.")

        # Create layer union table of big complex polygons.
        sql = ("CREATE TABLE {layer_union_table2} AS"
               "  (SELECT"
               "    {boundary_unit_column_name},"
               "    ST_MemUnion(geom) AS geom"
               "   FROM {layer_name}"
               "   WHERE ST_NPoints(geom) >= 500000"
               "   GROUP BY {boundary_unit_column_name}"
               "  )"
               )
        sql = sql.format(**sql_params)
        cursor.execute(sql)
        status.info("Created union table of complex polygons.")

        # Create union of the small simple polygons and big complex polygons.
        sql = ("CREATE TABLE {layer_union_table} AS"
               " SELECT"
               " u2.{boundary_unit_column_name},"
               " ST_MemUnion(u2.geom) AS geom FROM (SELECT {boundary_unit_column_name}, geom FROM {layer_union_table1} "
               " UNION "
               " SELECT {boundary_unit_column_name}, geom FROM {layer_union_table2}) u2"
               " GROUP BY u2.{boundary_unit_column_name}")
        sql = sql.format(**sql_params)
        cursor.execute(sql)
        status.info("Created union table of all layer polygons.")

        # Create table of gaps.
        sql = ("CREATE TABLE {gap_warning_table} AS"
               " SELECT"
               "  layer_union.{boundary_unit_column_name} AS {boundary_unit_column_name},"
               "  (ST_Dump(ST_Difference(boundary_union.geom, layer_union.geom))).geom AS geom"
               " FROM {layer_union_table} AS layer_union"
               " INNER JOIN {boundary_union_table} AS boundary_union"
               " USING ({boundary_unit_column_name});")
        sql = sql.format(**sql_params)
        cursor.execute(sql)


        # Report gaps.
        if cursor.rowcount > 0:
            status.info("Layer {:s} has {:d} gap(s).".format(layer_def["pg_layer_name"], cursor.rowcount))
            status.add_full_table(sql_params["gap_warning_table"])

        # Create table of excessive items.
        sql = ("CREATE TABLE {unit_warning_table} AS"
               " SELECT"
               "  layer.{boundary_unit_column_name},"
               "  layer.geom"
               " FROM {layer_name} AS layer"
               " WHERE"
               "  layer.{boundary_unit_column_name} IS NULL"
               "  OR layer.{boundary_unit_column_name} NOT IN (SELECT {boundary_unit_column_name} FROM {boundary_name});")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report excessive items.
        if cursor.rowcount > 0:
            status.info("Layer {:s} has {:d} feature(s) of unknown boundary unit."
                        .format(layer_def["pg_layer_name"], cursor.rowcount))
            status.add_full_table(sql_params["unit_warning_table"])
