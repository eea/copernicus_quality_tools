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

        # Create table of error items: features containing at least one interior ring (island)
        # whose area is smaller than MMU.
        # ST_Dump handles both Polygon and MultiPolygon by decomposing into individual polygons.
        # ST_DumpRings returns all rings; path[1] == 0 is the exterior ring, path[1] > 0 are interior rings.
        # ST_MakePolygon converts the ring linestring to a polygon so ST_Area can be computed.
        sql = ("CREATE TABLE {error_table} AS"
               " SELECT DISTINCT layer.{fid_name}"
               " FROM {layer_name} AS layer,"
               "  ST_Dump(layer.geom) AS dp,"
               "  ST_DumpRings((dp).geom) AS ring"
               " WHERE (ring).path[1] > 0"
               "  AND ST_Area(ST_BuildArea((ring).geom)) < {mmu};")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report error items.
        items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.failed("Layer {:s} has features with an interior ring smaller than MMU with {:s}: {:s}."
                         .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

            # Create detail table with the geometries of the offending small islands.
            sql = ("CREATE TABLE {detail_table} AS"
                   " SELECT"
                   "  layer.{fid_name},"
                   "  ST_SetSRID(ST_BuildArea((ring).geom), ST_SRID(layer.geom)) AS geom,"
                   "  ST_Area(ST_BuildArea((ring).geom)) AS area"
                   " FROM {layer_name} AS layer,"
                   "  ST_Dump(layer.geom) AS dp,"
                   "  ST_DumpRings((dp).geom) AS ring"
                   " WHERE (ring).path[1] > 0"
                   "  AND ST_Area(ST_BuildArea((ring).geom)) < {mmu};")
            sql = sql.format(**sql_params)
            cursor.execute(sql)

            # Report detail table.
            status.add_full_table(sql_params["detail_table"])
