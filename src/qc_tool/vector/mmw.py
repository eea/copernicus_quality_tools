#!/usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Minimum mapping width"
IS_SYSTEM = False


def run_check(params, status):
    from qc_tool.vector.helper import do_layers
    from qc_tool.vector.helper import get_failed_items_message

    cursor = params["connection_manager"].get_connection().cursor()

    for layer_def in do_layers(params):
        
        # Check for number of polygons in vector layer
        sql_params = {"layer_name": layer_def["pg_layer_name"]}
        sql = "SELECT EXISTS (SELECT 1 FROM {layer_name});"
        sql = sql.format(**sql_params)
        cursor.execute(sql)
        any_polygon_in_vector = cursor.fetchone()[0]
        if not any_polygon_in_vector:
            status.info("There is no polygon to check in the {:s} layer.".format(layer_def["pg_layer_name"]))
            continue

        # Prepare parameters used in sql clauses.
        sql_params = {"fid_name": layer_def["pg_fid_name"],
                      "layer_name": layer_def["pg_layer_name"],
                      "general_where": params["general_where"],
                      "exception_where": params["exception_where"],
                      "general_table": "s{:02d}_{:s}_general".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "exception_table": "s{:02d}_{:s}_exception".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "warning_table": "s{:02d}_{:s}_warning".format(params["step_nr"], layer_def["pg_layer_name"])}

        # Create table of general items.
        sql = ("CREATE TABLE {general_table} AS\n"
               "SELECT {fid_name}\n"
               "FROM {layer_name} AS layer\n"
               "WHERE\n"
               " ({general_where})\n"
               " OR ST_NumGeometries(ST_Buffer(geom, %(buffer)s)) = 1;")
        sql = sql.format(**sql_params)
        cursor.execute(sql, {"buffer": -params["mmw"] / 2})

        # Create table of exception items.
        sql = ("CREATE TABLE {exception_table} AS\n"
               "SELECT layer.{fid_name}\n"
               "FROM\n"
               " {layer_name} AS layer\n"
               " LEFT JOIN {general_table} AS gen ON layer.{fid_name} = gen.{fid_name}\n"
               "WHERE\n"
               " gen.{fid_name} IS NULL\n"
               " AND ({exception_where});")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report exception features.
        items_message = get_failed_items_message(cursor, sql_params["exception_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.info("Layer {:s} has exception features with {:s}: {:s}."
                        .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["exception_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

        # Create table of warning items.
        sql = ("CREATE TABLE {warning_table} AS\n"
               "SELECT layer.{fid_name}\n"
               "FROM\n"
               " {layer_name} AS layer\n"
               " LEFT JOIN {general_table} AS gen ON layer.{fid_name} = gen.{fid_name}\n"
               " LEFT JOIN {exception_table} AS exc ON layer.{fid_name} = exc.{fid_name}\n"
               "WHERE\n"
               " gen.{fid_name} IS NULL\n"
               " AND exc.{fid_name} IS NULL;")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report warning features.
        items_message = get_failed_items_message(cursor, sql_params["warning_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.info("Layer {:s} has warning features with {:s}: {:s}."
                        .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["warning_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])
