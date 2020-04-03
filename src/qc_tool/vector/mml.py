#!/usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Minimum mapping length."
IS_SYSTEM = False


def run_check(params, status):
    from qc_tool.vector.helper import do_layers
    from qc_tool.vector.helper import get_failed_items_message

    cursor = params["connection_manager"].get_connection().cursor()

    for layer_def in do_layers(params):
        # Prepare parameters used in sql clauses.
        sql_params = {"fid_name": layer_def["pg_fid_name"],
                      "layer_name": layer_def["pg_layer_name"],
                      "warning_where": params["warning_where"],
                      "warning_table": "s{:02d}_{:s}_warning".format(params["step_nr"], layer_def["pg_layer_name"])}

        # Create table of warning items.
        sql = ("CREATE TABLE {warning_table} AS\n"
               "SELECT {fid_name}\n"
               "FROM\n"
               " (SELECT {fid_name}, geom\n"
               "  FROM\n"
               "   (SELECT\n"
               "     {fid_name},\n"
               "     ST_Boundary(ST_OrientedEnvelope(geom)) AS env,\n"
               "     geom\n"
               "    FROM {layer_name} AS layer\n"
               "    WHERE {warning_where}\n"
               "   ) AS tenv\n"
               "  WHERE\n"
               "   greatest(ST_Distance(ST_PointN(env, 1), ST_PointN(env, 2)),\n"
               "            ST_Distance(ST_PointN(env, 2), ST_PointN(env, 3))) < %(mml)s\n"
               " ) AS tdist\n"
               "WHERE\n"
               " ST_Length(ST_ApproximateMedialAxis(ST_MakePolygon(ST_ExteriorRing(geom)))) <= %(mml)s;")
        sql = sql.format(**sql_params)
        cursor.execute(sql, {"mml": params["mml"]})

        # Report warning features.
        items_message = get_failed_items_message(cursor, sql_params["warning_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.info("Layer {:s} has warning features with {:s}: {:s}."
                        .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["warning_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])
