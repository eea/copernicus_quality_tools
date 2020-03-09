#!/usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Minimum mapping unit, Coastal zones."
IS_SYSTEM = False


def run_check(params, status):
    from qc_tool.vector.helper import do_layers
    from qc_tool.vector.helper import get_failed_items_message
    from qc_tool.vector.helper import MetaTable
    from qc_tool.vector.helper import NeighbourTable
    from qc_tool.vector.helper import create_others
    from qc_tool.vector.helper import create_has_comment

    cursor = params["connection_manager"].get_connection().cursor()

    for layer_def in do_layers(params):
        neighbour_table_name = "nb_{:s}".format(layer_def["pg_layer_name"])

        # Prepare parameters used in sql clauses.
        sql_params = {"meta_table_name": "meta_{:s}".format(layer_def["pg_layer_name"]),
                      "layer_name": layer_def["pg_layer_name"],
                      "fid_name": layer_def["pg_fid_name"],
                      "general_table": "s{:02d}_{:s}_general".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "exception_table": "s{:02d}_{:s}_exception".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "warning_table": "s{:02d}_{:s}_warning".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "error_table": "s{:02d}_{:s}_error".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "general_where": params["general_where"],
                      "exception_where": params["exception_where"],
                      "warning_where": params["warning_where"]}

        # Prepare support data.
        neighbour_table = NeighbourTable(cursor.connection,
                                         neighbour_table_name,
                                         layer_def["pg_layer_name"],
                                         layer_def["pg_fid_name"])
        neighbour_table.create()
        neighbour_table.fill()
        meta_table = MetaTable(cursor.connection,
                               sql_params["meta_table_name"],
                               layer_def["pg_layer_name"],
                               layer_def["pg_fid_name"])
        meta_table.create()
        meta_table.fill_margin()
        if params["complex_change"] is not None:
            meta_table.fill_complex_change(neighbour_table_name,
                                           params["complex_change"]["initial_code_column_name"],
                                           params["complex_change"]["final_code_column_name"],
                                           params["complex_change"]["area_column_name"])
        create_others(cursor.connection, neighbour_table_name, layer_def["pg_layer_name"], layer_def["pg_fid_name"])
        create_has_comment(cursor.connection)

        # Create table of general items.
        sql = "CREATE TABLE {general_table} ({fid_name} integer PRIMARY KEY);"
        sql = sql.format(**sql_params)
        cursor.execute(sql)
        sql = ("INSERT INTO {general_table}\n"
               " SELECT layer.{fid_name}\n"
               " FROM\n"
               "  {layer_name} AS layer\n"
               "   INNER JOIN {meta_table_name} AS meta ON layer.{fid_name} = meta.fid\n"
               " WHERE\n"
               "  {general_where};")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Create table of exception items.
        sql = ("CREATE TABLE {exception_table} ({fid_name} integer PRIMARY KEY);")
        sql = sql.format(**sql_params)
        cursor.execute(sql)
        sql = ("INSERT INTO {exception_table}\n"
               " SELECT layer.{fid_name}\n"
               " FROM\n"
               "  {layer_name} AS layer\n"
               "   INNER JOIN {meta_table_name} AS meta ON layer.{fid_name} = meta.fid\n"
               " WHERE\n"
               "  layer.{fid_name} NOT IN (SELECT {fid_name} FROM {general_table})\n"
               "  AND ({exception_where});")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report exception items.
        items_message = get_failed_items_message(cursor, sql_params["exception_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.info("Layer {:s} has exception features with {:s}: {:s}."
                        .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["exception_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

        # Create table of warning items.
        sql = ("CREATE TABLE {warning_table} ({fid_name} integer PRIMARY KEY);")
        sql = sql.format(**sql_params)
        cursor.execute(sql)
        sql = ("INSERT INTO {warning_table}\n"
               " SELECT layer.{fid_name}\n"
               " FROM\n"
               "  {layer_name} AS layer\n"
               "   INNER JOIN {meta_table_name} AS meta ON layer.{fid_name} = meta.fid\n"
               " WHERE\n"
               "  layer.{fid_name} NOT IN (SELECT {fid_name} FROM {general_table})\n"
               "  AND layer.{fid_name} NOT IN (SELECT {fid_name} FROM {exception_table})\n"
               "  AND ({warning_where});")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report warning items.
        items_message = get_failed_items_message(cursor, sql_params["warning_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.info("Layer {:s} has warning features with {:s}: {:s}."
                        .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["warning_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

        # Create table of error items.
        sql = ("CREATE TABLE {error_table} ({fid_name} integer PRIMARY KEY);")
        sql = sql.format(**sql_params)
        cursor.execute(sql)
        sql = ("INSERT INTO {error_table}\n"
               " SELECT {fid_name}\n"
               " FROM\n"
               "  {layer_name} AS layer\n"
               " WHERE\n"
               "  layer.{fid_name} NOT IN (SELECT {fid_name} FROM {general_table})\n"
               "  AND layer.{fid_name} NOT IN (SELECT {fid_name} FROM {exception_table})\n"
               "  AND layer.{fid_name} NOT IN (SELECT {fid_name} FROM {warning_table});")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report error items.
        items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.failed("Layer {:s} has error features with {:s}: {:s}."
                        .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

