#!/usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "The area of any island is greater than MMU."
IS_SYSTEM = False


def run_check(params, status):
    from qc_tool.vector.helper import do_layers
    from qc_tool.vector.helper import get_failed_items_message

    # Check if the current delivery is excluded from vector checks
    if "skip_vector_checks" in params:
        if params["skip_vector_checks"]:
            status.info("The delivery has been excluded from vector.geometry check because the vector data source does not contain a single object of interest.")
            return

    mmu = params["mmu"]

    cursor = params["connection_manager"].get_connection().cursor()

    for layer_def in do_layers(params):
        # Prepare parameters used in sql clauses.
        sql_params = {"fid_name": layer_def["pg_fid_name"],
                      "layer_name": layer_def["pg_layer_name"],
                      "error_table": "s{:02d}_{:s}_error".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "detail_table": "s{:02d}_{:s}_detail".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "mmu": mmu}

        # Inspect geometry type of the current layer
        sql = "SELECT GeometryType(geom) FROM {:s} LIMIT 1;".format(layer_def["pg_layer_name"])
        cursor.execute(sql)
        row = cursor.fetchone()
        geom_type = row[0].upper() if row else ""

        is_line_layer = "LINESTRING" in geom_type

        if is_line_layer:
            # SQL for LineString / MultiLineString layers
            # ST_Node ensures self-intersections and loops are split at vertices
            # ST_Polygonize turns enclosed loops into polygon geometries
            sql_error = (
                "CREATE TABLE {error_table} AS "
                "WITH noded AS ("
                "  SELECT {fid_name}, ST_Node(geom) AS geom FROM {layer_name}"
                "), "
                "polygons AS ("
                "  SELECT {fid_name}, (ST_Dump(ST_Polygonize(geom))).geom AS poly_geom "
                "  FROM noded GROUP BY {fid_name}"
                ") "
                "SELECT DISTINCT {fid_name} "
                "FROM polygons "
                "WHERE ST_Area(poly_geom) < {mmu};"
            )

            sql_detail = (
                "CREATE TABLE {detail_table} AS "
                "WITH noded AS ("
                "  SELECT {fid_name}, ST_Node(geom) AS geom FROM {layer_name}"
                "), "
                "polygons AS ("
                "  SELECT {fid_name}, (ST_Dump(ST_Polygonize(geom))).geom AS poly_geom "
                "  FROM noded GROUP BY {fid_name}"
                ") "
                "SELECT "
                "  {fid_name}, "
                "  poly_geom AS geom, "
                "  ST_Area(poly_geom) AS area "
                "FROM polygons "
                "WHERE ST_Area(poly_geom) < {mmu};"
            )
        else:
            # Original SQL for Polygon / MultiPolygon layers
            sql_error = (
                "CREATE TABLE {error_table} AS"
                " SELECT DISTINCT layer.{fid_name}"
                " FROM {layer_name} AS layer,"
                "  ST_Dump(layer.geom) AS dp,"
                "  ST_DumpRings((dp).geom) AS ring"
                " WHERE (ring).path[1] > 0"
                "  AND ST_Area(ST_BuildArea((ring).geom)) < {mmu};"
            )

            sql_detail = (
                "CREATE TABLE {detail_table} AS"
                " SELECT"
                "  layer.{fid_name},"
                "  ST_SetSRID(ST_BuildArea((ring).geom), ST_SRID(layer.geom)) AS geom,"
                "  ST_Area(ST_BuildArea((ring).geom)) AS area"
                " FROM {layer_name} AS layer,"
                "  ST_Dump(layer.geom) AS dp,"
                "  ST_DumpRings((dp).geom) AS ring"
                " WHERE (ring).path[1] > 0"
                "  AND ST_Area(ST_BuildArea((ring).geom)) < {mmu};"
            )

        # Execute error table query
        cursor.execute(sql_error.format(**sql_params))

        # Report error items.
        items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.failed("Layer {:s} has features with an interior ring/enclosed loop smaller than MMU with {:s}: {:s}."
                          .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

            # Execute detail table query
            cursor.execute(sql_detail.format(**sql_params))

            # Report detail table.
            status.add_full_table(sql_params["detail_table"])