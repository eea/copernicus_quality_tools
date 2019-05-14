#!/usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "There is no gap in the AOI."
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
                      "warning_table": "s{:02d}_{:s}_gap_warning".format(params["step_nr"], layer_def["pg_layer_name"])}

        # Create table of error items.
        sql = ("CREATE TABLE {warning_table} AS"
               " SELECT"
               "  (ST_Dump(ST_Difference(boundary_union.geom, layer_union.geom))).geom AS geom"
               " FROM"
               "  (SELECT ST_Union(wkb_geometry) AS geom FROM {layer_name}) AS layer_union,"
               "  (SELECT ST_Union(wkb_geometry) AS geom FROM {boundary_name}) AS boundary_union;")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report error items.
        if cursor.rowcount > 0:
            status.info("Layer {:s} has {:d} gaps.".format(layer_def["pg_layer_name"], cursor.rowcount))
            status.add_full_table(sql_params["warning_table"])
