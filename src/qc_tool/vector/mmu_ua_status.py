#!/usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Minimum mapping unit, Urban Atlas status layer."
IS_SYSTEM = False


def run_check(params, status):
    from qc_tool.vector.helper import do_layers
    from qc_tool.vector.helper import get_failed_items_message

    cursor = params["connection_manager"].get_connection().cursor()

    for layer_def in do_layers(params):
        # Prepare parameters used in sql clauses.
        sql_params = {"fid_name": layer_def["pg_fid_name"],
                      "layer_name": layer_def["pg_layer_name"],
                      "area_column_name": params["area_column_name"],
                      "code_column_name": params["code_column_name"],
                      "general_table": "s{:02d}_{:s}_general".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "exception_table": "s{:02d}_{:s}_exception".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "warning_table": "s{:02d}_{:s}_warning".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "error_table": "s{:02d}_{:s}_error".format(params["step_nr"], layer_def["pg_layer_name"])}

        # Create table of general items.
        sql = ("CREATE TABLE {general_table} AS\n"
               "SELECT {fid_name}\n"
               "FROM {layer_name}\n"
               "WHERE\n"
               " {code_column_name} LIKE '122%'\n"
               " OR ({code_column_name} LIKE '1%' AND {area_column_name} >= 2500)\n"
               " OR ({code_column_name} SIMILAR TO '[2-5]%' AND {area_column_name} >= 10000)\n"
               " OR {code_column_name} LIKE '9%';")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Create table of exception items.
        # Items touching boundary.
        sql = ("CREATE TABLE {exception_table} AS\n"
               "SELECT layer.{fid_name}\n"
               "FROM\n"
               " {layer_name} AS layer\n"
               " LEFT JOIN {general_table} AS gen ON layer.{fid_name} = gen.{fid_name}\n"
               " INNER JOIN (SELECT ST_Boundary(ST_Union(geom)) AS geom\n"
               "             FROM {layer_name}) AS boundary ON layer.geom && boundary.geom\n"
               "WHERE\n"
               " gen.{fid_name} IS NULL\n"
               " AND layer.{area_column_name} >= 100\n"
               " AND ST_Dimension(ST_Intersection(layer.geom, boundary.geom)) >= 1;")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Items with specific comment.
        exception_comments = params.get("exception_comments", [])
        for exception_comment in exception_comments:
            sql = ("INSERT INTO {exception_table}\n"
                   "SELECT layer.{fid_name}\n"
                   "FROM\n"
                   " {layer_name} AS layer\n"
                   " LEFT JOIN {general_table} AS gen ON layer.{fid_name} = gen.{fid_name}\n"
                   " LEFT JOIN {exception_table} AS exc ON layer.{fid_name} = exc.{fid_name}\n"
                   "WHERE\n"
                   " gen.{fid_name} IS NULL\n"
                   " AND exc.{fid_name} IS NULL\n"
                   " AND layer.{comment_column_name} LIKE '%{exception_comment}%';")
            sql_params["comment_column_name"] = params["comment_column_name"]
            sql_params["exception_comment"] = exception_comment
            sql = sql.format(**sql_params)
            cursor.execute(sql)

        # Items touching cloud.
        sql = ("INSERT INTO {exception_table}\n"
               "SELECT layer.{fid_name}\n"
               "FROM\n"
               " {layer_name} AS layer\n"
               " LEFT JOIN {general_table} AS gen ON layer.{fid_name} = gen.{fid_name}\n"
               " LEFT JOIN {exception_table} AS exc ON layer.{fid_name} = exc.{fid_name}\n"
               " INNER JOIN {layer_name} AS cloud ON layer.geom && cloud.geom\n"
               "WHERE\n"
               " gen.{fid_name} IS NULL\n"
               " AND exc.{fid_name} IS NULL\n"
               " AND layer.{code_column_name} NOT LIKE '9%'\n"
               " AND cloud.{code_column_name} LIKE '9%'\n"
               " AND ST_Dimension(ST_Intersection(layer.geom, cloud.geom)) >= 1;")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report exception items.
        items_message = get_failed_items_message(cursor, sql_params["exception_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.info("Layer {:s} has exception features with {:s}: {:s}."
                        .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["exception_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

        # Create table of warning items.
        sql = ("CREATE TABLE {warning_table} AS\n"
               "SELECT DISTINCT layer.{fid_name}\n"
               "FROM\n"
               " {layer_name} AS layer\n"
               " LEFT JOIN {general_table} AS gen ON layer.{fid_name} = gen.{fid_name}\n"
               " LEFT JOIN {exception_table} AS exc ON layer.{fid_name} = exc.{fid_name}\n"
               " INNER JOIN {layer_name} AS road ON layer.geom && road.geom\n"
               "WHERE\n"
               " gen.{fid_name} IS NULL\n"
               " AND exc.{fid_name} IS NULL\n"
               " AND layer.{area_column_name} >= 500\n"
               " AND layer.{code_column_name} NOT LIKE '122%'\n"
               " AND road.{code_column_name} LIKE '122%'\n"
               " AND ST_Dimension(ST_Intersection(layer.geom, road.geom)) >= 1;")
        sql = sql.format(**sql_params)
        cursor.execute(sql)
            
        # Report warning items.
        items_message = get_failed_items_message(cursor, sql_params["warning_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.info("Layer {:s} has warning features with {:s}: {:s}."
                        .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["warning_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

        # Create table of error items.
        sql = ("CREATE TABLE {error_table} AS\n"
               "SELECT layer.{fid_name}\n"
               "FROM\n"
               " {layer_name} AS layer\n"
               " LEFT JOIN {general_table} AS gen ON layer.{fid_name} = gen.{fid_name}\n"
               " LEFT JOIN {exception_table} AS exc ON layer.{fid_name} = exc.{fid_name}\n"
               " LEFT JOIN {warning_table} AS warn ON layer.{fid_name} = warn.{fid_name}\n"
               "WHERE\n"
               " gen.{fid_name} IS NULL\n"
               " AND exc.{fid_name} IS NULL\n"
               " AND warn.{fid_name} IS NULL;")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report error items.
        items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.failed("Layer {:s} has error features with {:s}: {:s}."
                          .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])
