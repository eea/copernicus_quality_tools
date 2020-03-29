#!/usr/bin/env python3
# -*- coding: utf-8 -*-


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
        sql = ("CREATE TABLE {general_table} AS\n"
               "SELECT {fid_name}\n"
               "FROM {layer_name}\n"
               "WHERE {area_column_name} >= {area_ha};")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Create table of exception items.
        # Linear features.
        sql = ("CREATE TABLE {exception_table} AS\n"
               "SELECT layer.{fid_name}\n"
               "FROM\n"
               " {layer_name} AS layer\n"
               " LEFT JOIN {general_table} AS gen ON layer.{fid_name} = gen.{fid_name}\n"
               "WHERE\n"
               " gen.{fid_name} IS NULL\n"
               " AND layer.{area_column_name} >= 0.1\n"
               " AND layer.{code_column_name}::text SIMILAR TO '(121|122|911|912)%';")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Marginal features.
        sql = ("INSERT INTO {exception_table}\n"
               "SELECT layer.{fid_name}\n"
               "FROM\n"
               " {layer_name} AS layer\n"
               " LEFT JOIN {general_table} AS gen ON layer.{fid_name} = gen.{fid_name}\n"
               " LEFT JOIN {exception_table} AS exc ON layer.{fid_name} = exc.{fid_name}\n"
               " CROSS JOIN (SELECT ST_Boundary(ST_Union(geom)) AS geom FROM {layer_name}) AS margin\n"
               "WHERE\n"
               " gen.{fid_name} IS NULL\n"
               " AND exc.{fid_name} IS NULL\n"
               " AND layer.{area_column_name} >= 0.1\n"
               " AND ST_Dimension(ST_Intersection(layer.geom, margin.geom)) >= 1;")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Urban features touching road or railway.
        sql = ("INSERT INTO {exception_table}\n"
               "SELECT layer.{fid_name}\n"
               "FROM\n"
               " {layer_name} AS layer\n"
               " LEFT JOIN {general_table} AS gen ON layer.{fid_name} = gen.{fid_name}\n"
               " LEFT JOIN {exception_table} AS exc ON layer.{fid_name} = exc.{fid_name}\n"
               " CROSS JOIN (SELECT * FROM {layer_name} WHERE {code_column_name}::text SIMILAR TO '(121|122)%') AS randr\n"
               "WHERE\n"
               " gen.{fid_name} IS NULL\n"
               " AND exc.{fid_name} IS NULL\n"
               " AND layer.{area_column_name} >= 0.25\n"
               " AND layer.{code_column_name}::text LIKE '1%'\n"
               " AND layer.{code_column_name}::text NOT SIMILAR TO '(10|121|122)%'\n"
               " AND layer.geom && randr.geom\n"
               " AND ST_Dimension(ST_Intersection(layer.geom, randr.geom)) >= 1;")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

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

        # Add exceptions comming from complex change.
        # Do that once for initial code and once again for final code.
        for code_column_name in (params["initial_code_column_name"],
                                 params["final_code_column_name"]):

            # Find potential bad fids.
            sql = ("SELECT layer.{fid_name}\n"
                   "FROM\n"
                   " {layer_name} AS layer\n"
                   " LEFT JOIN {general_table} AS gen ON layer.{fid_name} = gen.{fid_name}\n"
                   " LEFT JOIN {exception_table} AS exc ON layer.{fid_name} = exc.{fid_name}\n"
                   "WHERE\n"
                   " gen.{fid_name} IS NULL\n"
                   " AND exc.{fid_name} IS NULL;")
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
            sql = ("INSERT INTO {exception_table}\n"
                   "SELECT ct.fid\n"
                   "FROM\n"
                   " {cluster_table} AS ct\n"
                   " INNER JOIN (SELECT cluster_id\n"
                   "             FROM\n"
                   "              {cluster_table} AS cct\n"
                   "              INNER JOIN {layer_name} AS clr ON cct.fid = clr.{fid_name}\n"
                   "             GROUP BY cluster_id\n"
                   "             HAVING sum(clr.{area_column_name}) > 0.5) AS area_ct ON ct.cluster_id = area_ct.cluster_id\n"
                   " LEFT JOIN {general_table} AS gen ON ct.fid = gen.{fid_name}\n"
                   " LEFT JOIN {exception_table} AS exc ON ct.fid = exc.{fid_name}\n"
                   "WHERE\n"
                   " gen.{fid_name} IS NULL\n"
                   " AND exc.{fid_name} IS NULL;")
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
