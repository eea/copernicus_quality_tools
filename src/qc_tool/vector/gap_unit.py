#!/usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "There is no gap in the set of AOIs."
IS_SYSTEM = False


POLYGON_MAX_POINTS = 500000
BIG_POLYGON_AREA_TOLERANCE = 0.1


def run_check(params, status):
    from qc_tool.vector.helper import do_layers

    cursor = params["connection_manager"].get_connection().cursor()

    if "boundary" not in params["layer_defs"]:
        status.info("Check cancelled due to boundary not being available.")
        return

    for layer_def in do_layers(params):
        # Prepare parameters used in sql clauses.
        sql_params = {"layer_name": layer_def["pg_layer_name"],
                      "boundary_name": params["layer_defs"]["boundary"]["pg_layer_name"],
                      "boundary_unit_column_name": params["boundary_unit_column_name"],
                      "polygon_max_points": POLYGON_MAX_POINTS,
                      "big_polygon_area_tolerance": BIG_POLYGON_AREA_TOLERANCE,
                      "boundary_union_table": "s{:02d}_{:s}_boundary_union_table".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "layer_union_table": "s{:02d}_{:s}_layer_union_table".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "big_polygon_table": "s{:02d}_{:s}_big_polygon_table".format(params["step_nr"], layer_def["pg_layer_name"]),
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


        # Create layer union table of normally sized polygons.
        sql = ("CREATE TABLE {layer_union_table} AS"
               "  (SELECT"
               "    {boundary_unit_column_name},"
               "    ST_Buffer(ST_Collect(geom), 0) AS geom"
               "   FROM {layer_name}"
               "   WHERE ST_NPoints(geom) <= {polygon_max_points}"
               "   GROUP BY {boundary_unit_column_name}"
               "  )"
               )
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Are there any large complex polygons with number of vertices > POLYGON_MAX_POINTS?
        sql = "SELECT MAX(ST_NPoints(geom)) FROM {layer_name}"
        sql = sql.format(**sql_params)
        cursor.execute(sql)
        layer_npoints_max = float(cursor.fetchone()[0])

        if layer_npoints_max <= POLYGON_MAX_POINTS:
            # Normal case, layer does not have any polygon with extremely large number of vertices.
            # Create table of all gaps.
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

        else:
            # Special case, layer has polygons with large number of points.

            # Create union table of polygons with extremely large numbers of vertices.
            sql = ("CREATE TABLE {big_polygon_table} AS"
                   "  (SELECT"
                   "    {boundary_unit_column_name},"
                   "    ST_MemUnion(geom) AS geom"
                   "   FROM {layer_name}"
                   "   WHERE ST_NPoints(geom) > {polygon_max_points}"
                   "   GROUP BY {boundary_unit_column_name}"
                   "  )"
                   )
            sql = sql.format(**sql_params)
            cursor.execute(sql)

            # Create table of suspect gaps.
            sql = ("CREATE TABLE {gap_suspect_table} AS"
                   " SELECT"
                   "  layer_union.{boundary_unit_column_name} AS {boundary_unit_column_name},"
                   "  (ST_Difference(boundary_union.geom, layer_union.geom)) AS geom"
                   " FROM {layer_union_table} AS layer_union"
                   " INNER JOIN {boundary_union_table} AS boundary_union"
                   " USING ({boundary_unit_column_name});")
            sql = sql.format(**sql_params)
            cursor.execute(sql)

            # Verify if any of the suspect gaps is co-incident with any of the extremely complex polygons.
            # The non-coincident suspect gaps are reported a real gaps.
            sql = ("CREATE TABLE {gap_warning_table} AS"
                   " SELECT"
                   " suspect_gaps.{boundary_unit_column_name} AS {boundary_unit_column_name},"
                   " suspect_gaps.geom as geom,"
                   " big_polygons.{boundary_unit_column_name} AS found_polygon"
                   " FROM {gap_suspect_table} AS suspect_gaps"
                   " LEFT JOIN {big_polygon_table} AS big_polygons"
                   " ON ABS(ST_Area(suspect_gaps.geom) - ST_AREA(big_polygons.geom)) < {big_polygon_area_tolerance}"
                   " WHERE big_polygons.{boundary_unit_column_name} IS NULL;")

            sql = sql.format(**sql_params)
            cursor.execute(sql)

            # Report gaps.
            if cursor.rowcount > 0:
                status.info("Layer {:s} has {:d} gap(s).".format(layer_def["pg_layer_name"], cursor.rowcount))
                status.add_full_table(sql_params["gap_warning_table"])
                return

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
