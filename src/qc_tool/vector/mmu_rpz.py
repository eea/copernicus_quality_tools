#!/usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Minimum mapping unit, Riparian zones."
IS_SYSTEM = False


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
                      "urban_area_ha": params["urban_area_ha"],
                      "marginal_area_ha": params["marginal_area_ha"],
                      "linear_area_ha": params["linear_area_ha"],
                      "code_column_name": params["code_column_name"],
                      "general_table": "s{:02d}_{:s}_general".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "exception_table": "s{:02d}_{:s}_exception".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "error_table": "s{:02d}_{:s}_error".format(params["step_nr"], layer_def["pg_layer_name"])}

        # Create table of general items.
        sql = ("CREATE TABLE {general_table} AS\n"
               "SELECT {fid_name}\n"
               "FROM {layer_name}\n"
               "WHERE\n"
               " ua IS NOT NULL\n"
               " OR {area_column_name} >= {area_ha};")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Create table of exception items.
        # Marginal features.
        sql = ("CREATE TABLE {exception_table} AS\n"
               "SELECT layer.{fid_name}\n"
               "FROM\n"
               " {layer_name} AS layer\n"
               " LEFT JOIN {general_table} AS gen ON layer.{fid_name} = gen.{fid_name}\n"
               " INNER JOIN (SELECT ST_Boundary(ST_Union(geom)) AS geom\n"
               "             FROM {layer_name}\n"
               "             WHERE ua IS NULL) AS margin ON layer.geom && margin.geom\n"
               "WHERE\n"
               " gen.{fid_name} IS NULL\n"
               " AND layer.{area_column_name} >= {marginal_area_ha}\n"
               " AND ST_Dimension(ST_Intersection(layer.geom, margin.geom)) >= 1;")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Urban features.
        if len(params["urban_feature_codes"]) > 0:
            sql_execute_params = {"urban_feature_codes": tuple(params["urban_feature_codes"])}
            sql = ("INSERT INTO {exception_table}\n"
                   "SELECT layer.{fid_name}\n"
                   "FROM\n"
                   " {layer_name} AS layer\n"
                   " LEFT JOIN {general_table} AS gen ON layer.{fid_name} = gen.{fid_name}\n"
                   " LEFT JOIN {exception_table} AS exc ON layer.{fid_name} = exc.{fid_name}\n"
                   "WHERE\n"
                   " gen.{fid_name} IS NULL\n"
                   " AND exc.{fid_name} IS NULL\n"
                   " AND {area_column_name} >= {urban_area_ha}\n"
                   " AND {code_column_name} IN %(urban_feature_codes)s;")
            sql = sql.format(**sql_params)
            cursor.execute(sql, sql_execute_params)

        # Linear features.
        if len(params["linear_feature_codes"]) > 0:
            sql_execute_params = {"linear_feature_codes": tuple(params["linear_feature_codes"])}
            sql = ("INSERT INTO {exception_table}\n"
                   "SELECT layer.{fid_name}\n"
                   "FROM\n"
                   " {layer_name} AS layer\n"
                   " LEFT JOIN {general_table} AS gen ON layer.{fid_name} = gen.{fid_name}\n"
                   " LEFT JOIN {exception_table} AS exc ON layer.{fid_name} = exc.{fid_name}\n"
                   "WHERE\n"
                   " gen.{fid_name} IS NULL\n"
                   " AND exc.{fid_name} IS NULL\n"
                   " AND layer.{area_column_name} >= {linear_area_ha}\n"
                   " AND layer.{code_column_name} IN %(linear_feature_codes)s;")
            sql = sql.format(**sql_params)
            cursor.execute(sql, sql_execute_params)

        # Features with specific comments.
        if len(params["exception_comments"]) > 0:
            for exception_comment in params["exception_comments"]:
                for comment_column_name in params["comment_column_names"]:
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
                    sql_params["comment_column_name"] = comment_column_name
                    sql_params["exception_comment"] = exception_comment
                    sql = sql.format(**sql_params)
                    cursor.execute(sql)

        # Report exception items.
        items_message = get_failed_items_message(cursor, sql_params["exception_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.info("Layer {:s} has exception features with {:s}: {:s}."
                        .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["exception_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

        # Create table of error items.
        sql = ("CREATE TABLE {error_table} AS\n"
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

        # Report error items.
        items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.failed("Layer {:s} has error features with {:s}: {:s}."
                          .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])
