#!/usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "There is no gap in the set of AOIs."
IS_SYSTEM = False


def run_check(params, status):
    from qc_tool.vector.helper import do_layers
    from qc_tool.vector.helper import get_failed_items_message

    cursor = params["connection_manager"].get_connection().cursor()

    if "boundary" not in params["layer_defs"]:
        status.info("Check cancelled due to boundary not being available.")
        return

    for layer_def in do_layers(params):
        # Prepare parameters used in sql clauses.
        sql_params = {"layer_name": layer_def["pg_layer_name"],
                      "boundary_name": params["layer_defs"]["boundary"]["pg_layer_name"],
                      "boundary_unit_column_name": params["boundary_unit_column_name"],
                      "gap_warning_table": "s{:02d}_{:s}_gap_warning".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "unit_warning_table": "s{:02d}_{:s}_unit_warning".format(params["step_nr"], layer_def["pg_layer_name"])}

        # Create table of error items.
        sql = ("CREATE TABLE {gap_warning_table} AS"
               " SELECT"
               "  layer_union.{boundary_unit_column_name} AS {boundary_unit_column_name},"
               "  (ST_Dump(ST_Difference(boundary_union.geom, layer_union.geom))).geom AS geom"
               " FROM"
               "  (SELECT"
               "    {boundary_unit_column_name},"
               "    ST_Union(geom) AS geom"
               "   FROM {layer_name}"
               "   GROUP BY {boundary_unit_column_name}"
               "  ) AS layer_union"
               " INNER JOIN"
               "  (SELECT"
               "    {boundary_unit_column_name},"
               "    ST_Union(geom) AS geom"
               "   FROM {boundary_name}"
               "   WHERE {boundary_unit_column_name} IN (SELECT {boundary_unit_column_name} FROM {layer_name})"
               "   GROUP BY {boundary_unit_column_name}"
               "  ) AS boundary_union"
               " USING ({boundary_unit_column_name});")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report error items.
        if cursor.rowcount > 0:
            status.info("Layer {:s} has {:d} gap(s).".format(layer_def["pg_layer_name"], cursor.rowcount))
            status.add_full_table(sql_params["gap_warning_table"])

        # Find warning features.
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

        # Report warning items.
        if cursor.rowcount > 0:
            status.info("Layer {:s} has {:d} feature(s) of unknown boundary unit."
                        .format(layer_def["pg_layer_name"], cursor.rowcount))
            status.add_full_table(sql_params["unit_warning_table"])
