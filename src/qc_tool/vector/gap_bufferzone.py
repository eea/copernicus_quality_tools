#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import logging


DESCRIPTION = "There is no gap in the AOI."
IS_SYSTEM = False
DEFAULT_BOUNDARY_TOLERANCE = 0.01 # tolerance at the edge of the AOI in metres
DEFAULT_GAP_AREA_TOLERANCE = 0.000001 # square metres
DEFAULT_GAP_WIDTH_TOLERANCE = 0.00001 # square metres
DEFAULT_BOUNDARY_BUFFERZONE_WIDTH = 1100 # metres - if > 0, will report gaps in the buffer zone as exceptions, not errors. This is used e.g for clc2024  


log = logging.getLogger(__name__)


def run_check(params, status):
    from qc_tool.vector.helper import do_layers
    from qc_tool.vector.helper import GapTable
    from qc_tool.vector.helper import get_failed_items_message
    from qc_tool.vector.helper import PartitionedLayer

    if "boundary" not in params["layer_defs"]:
        status.cancelled("Check cancelled due to boundary not being available.")
        return

    # boundary_tolerance optional parameter - to allow higher tolerance near the boundar
    # e.g if the boundary is a less-accurate sea / ocean buffer boundary.
    boundary_tolerance = params.get("boundary_tolerance", DEFAULT_BOUNDARY_TOLERANCE)

    # special parameter for buffer zone width - to report gaps in the buffer zone
    # as exceptions, not errors. This is useful for CLC2024.    
    boundary_buffer_zone_width = params.get("boundary_buffer_zone_width", DEFAULT_BOUNDARY_BUFFERZONE_WIDTH)

    gap_area_tolerance = params.get("gap_area_tolerance", DEFAULT_GAP_AREA_TOLERANCE)
    gap_width_tolerance = params.get("gap_width_tolerance", DEFAULT_GAP_WIDTH_TOLERANCE)

    # Update boundary with negative tolerance buffer (if needed)
    boundary_table_name = params["layer_defs"]["boundary"]["pg_layer_name"]
    if boundary_tolerance > 0.0:
        sql_params_boundary = {"boundary_table": boundary_table_name,
                        "tolerance": boundary_tolerance}
        with params["connection_manager"].get_connection().cursor() as cursor:
            sql = "UPDATE {boundary_table} SET geom = ST_Multi(ST_BUFFER(geom, -{tolerance}));"
            sql = sql.format(**sql_params_boundary)
            cursor.execute(sql)

    # Create the boundary core table if needed (eg 1200 m inner buffer for CLC2024).
    boundary_core_table_name = f"{params['layer_defs']['boundary']['pg_layer_name']}_buffer"
    
    if boundary_buffer_zone_width > 0.0:
        sql_params_bufferzone = {"boundary_table": boundary_table_name,
                        "boundary_buffer_zone_width": boundary_buffer_zone_width,
                        "boundary_core_table": boundary_core_table_name}
        with params["connection_manager"].get_connection().cursor() as cursor:
   
            # Create the core table if it does not already exist.
            sql = ("CREATE TABLE IF NOT EXISTS {boundary_core_table} AS\n"
                "SELECT ST_Subdivide(ST_Multi(ST_Buffer(geom, -{boundary_buffer_zone_width})), 255) AS geom\n"
                "FROM {boundary_table};")

            sql = sql.format(**sql_params_bufferzone)
            cursor.execute(sql)

            # Add a spatial index to the core table
            sql_idx = "CREATE INDEX IF NOT EXISTS {boundary_core_table}_idx ON {boundary_core_table} USING GIST (geom);"
            cursor.execute(sql_idx.format(**sql_params_bufferzone))
    
    for layer_def in do_layers(params):
        log.debug("Started gap check for the layer {:s}.".format(layer_def["pg_layer_name"]))

        # Prepare support data.
        partitioned_layer = PartitionedLayer(params["connection_manager"].get_connection(),
                                             layer_def["pg_layer_name"],
                                             layer_def["pg_fid_name"])

        gap_table = GapTable(partitioned_layer,
                             params["layer_defs"]["boundary"]["pg_layer_name"],
                             params["du_column_name"])
        gap_table.make()

        # Prepare parameters used in sql clauses.
        sql_params = {"gap_table": gap_table.gap_table_name,
                      "boundary_core_table": boundary_core_table_name,
                      "small_gap_table": "s{:02d}_{:s}_gap_small".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "gap_bufferzone_large_exception_table": "s{:02d}_{:s}_gap_bufferzone_large_exception".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "gap_bufferzone_small_exception_table": "s{:02d}_{:s}_gap_bufferzone_small_exception".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "gap_interior_exception_table": "s{:02d}_{:s}_gap_interior_small_exception".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "gap_suspect_table": "s{:02d}_{:s}_gap_suspect".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "gap_error_table": "s{:02d}_{:s}_gap_error".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "gap_area_tolerance": str(gap_area_tolerance),
                      "gap_width_tolerance": str(gap_width_tolerance)}
        
        with params["connection_manager"].get_connection().cursor() as cursor:

            # Create table of small gap items (if we have high tolerance for gaps).
            if gap_area_tolerance > DEFAULT_GAP_AREA_TOLERANCE or gap_width_tolerance > DEFAULT_GAP_WIDTH_TOLERANCE:
                sql = ("CREATE TABLE {small_gap_table} AS\n"
                       "SELECT ROW_NUMBER() OVER () AS id, geom, ST_Area(geom) as area FROM {gap_table}\n"
                       "WHERE ST_AREA(geom) <= {gap_area_tolerance}\n"
                       "OR ST_MinimumClearance(geom) <= {gap_width_tolerance}\n"
                       "OR ST_XMAX(geom) - ST_XMIN(geom) <= {gap_width_tolerance}\n"
                       "OR ST_YMAX(geom) - ST_YMIN(geom) <= {gap_width_tolerance};")
                sql = sql.format(**sql_params)
                cursor.execute(sql)

                # Report small gap items - interior gaps that are smaller than the tolerances.
                sql_interior_small_exceptions = ("CREATE TABLE {gap_interior_exception_table} AS\n"
                              "SELECT DISTINCT s.geom, s.area, s.id FROM {small_gap_table} s\n"
                              "JOIN {boundary_core_table} c ON ST_Intersects(s.geom, c.geom);")
                cursor.execute(sql_interior_small_exceptions.format(**sql_params))
                if cursor.rowcount > 0:
                    status.info("Layer {:s} has {:d} interior small gap items with area <= {:s} or width <= {:s} tolerance."
                                .format(layer_def["pg_layer_name"], cursor.rowcount,
                                        str(gap_area_tolerance), str(gap_width_tolerance)))
                    # Report small gap table.
                    status.add_full_table(sql_params["gap_interior_exception_table"])

                # Report small gap items - buffer zone gaps that are smaller than the tolerances.
                sql_bufferzone_small_exceptions = ("CREATE TABLE {gap_bufferzone_small_exception_table} AS\n"
                                  "SELECT s.geom, s.area FROM {small_gap_table} s\n"
                                  "LEFT JOIN {gap_interior_exception_table} e ON s.id = e.id\n"
                                  "WHERE e.id IS NULL;")
                cursor.execute(sql_bufferzone_small_exceptions.format(**sql_params))
                if cursor.rowcount > 0:
                    status.info(f"Layer {layer_def['pg_layer_name']} has {cursor.rowcount} boundary buffer zone small gap items with area <= {gap_area_tolerance} or width <= {gap_width_tolerance} tolerance.")
                    status.add_full_table(sql_params["gap_bufferzone_small_exception_table"])


            # 1. Create Suspect Table (Potential Group 3 errors)
            # Added ST_Area here so it is available for later steps
            sql = ("CREATE TABLE {gap_suspect_table} AS\n"
                "SELECT ROW_NUMBER() OVER () AS id, geom, ST_Area(geom) as area FROM {gap_table}\n"
                "WHERE ST_AREA(geom) > {gap_area_tolerance}\n"
                "AND ST_MinimumClearance(geom) > {gap_width_tolerance}\n"
                "AND (ST_XMAX(geom) - ST_XMIN(geom) > {gap_width_tolerance}\n"
                "     AND ST_YMAX(geom) - ST_YMIN(geom) > {gap_width_tolerance});")
            sql = sql.format(**sql_params)
            cursor.execute(sql)

            # 2. Identify Interior core zone gaps (Real Errors)
            sql_errors = ("CREATE TABLE {gap_error_table} AS\n"
                            "SELECT DISTINCT s.geom, s.area, s.id FROM {gap_suspect_table} s\n"
                            "JOIN {boundary_core_table} c ON ST_Intersects(s.geom, c.geom);")
            cursor.execute(sql_errors.format(**sql_params))
            
            if cursor.rowcount > 0:
                status.failed("Layer {:s} has {:d} interior area real gaps.".format(layer_def["pg_layer_name"], cursor.rowcount))
                status.add_full_table(sql_params["gap_error_table"])

            # 3. Identify big gaps in the buffer zone (that do not intersect the core)
            sql_exceptions = ("CREATE TABLE {gap_bufferzone_large_exception_table} AS\n"
                                "SELECT s.geom, s.area FROM {gap_suspect_table} s\n"
                                "LEFT JOIN {gap_error_table} e ON s.id = e.id\n"
                                "WHERE e.id IS NULL;")
            cursor.execute(sql_exceptions.format(**sql_params))

            if cursor.rowcount > 0:
                status.info(f"Layer {layer_def['pg_layer_name']} has {cursor.rowcount} boundary buffer zone large gap items with area > {gap_area_tolerance} or width > {gap_width_tolerance} tolerance.")
                status.add_full_table(sql_params["gap_bufferzone_large_exception_table"])

        log.info("GAP check for the layer {:s} has been finished.".format(layer_def["pg_layer_name"]))
