#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging

DESCRIPTION = "There is no gap in the AOI."
IS_SYSTEM = False
DEFAULT_BOUNDARY_TOLERANCE = 0.01  # metres
DEFAULT_GAP_AREA_TOLERANCE = 0.000001  # square metres
DEFAULT_GAP_WIDTH_TOLERANCE = 0.00001  # metres
DEFAULT_BOUNDARY_BUFFERZONE_WIDTH = 1100  # metres

log = logging.getLogger(__name__)


def run_check(params, status):
    from qc_tool.vector.helper import GapTable, PartitionedLayer, do_layers

    if "boundary" not in params["layer_defs"]:
        status.cancelled("Check cancelled due to boundary not being available.")
        return

    boundary_tolerance = params.get("boundary_tolerance", DEFAULT_BOUNDARY_TOLERANCE)
    boundary_buffer_zone_width = params.get("boundary_buffer_zone_width", DEFAULT_BOUNDARY_BUFFERZONE_WIDTH)
    gap_area_tolerance = params.get("gap_area_tolerance", DEFAULT_GAP_AREA_TOLERANCE)
    gap_width_tolerance = params.get("gap_width_tolerance", DEFAULT_GAP_WIDTH_TOLERANCE)
    gap_negative_buffer = gap_width_tolerance * -0.5

    boundary_table_name = params["layer_defs"]["boundary"]["pg_layer_name"]
    boundary_core_table_name = f"{boundary_table_name}_core"

    # Total buffer shrink offset = boundary_tolerance + buffer_zone_width
    total_shrink = boundary_tolerance + boundary_buffer_zone_width

    # 1. Create Core Boundary Zone Table (without mutating original boundary)
    with params["connection_manager"].get_connection().cursor() as cursor:
        sql_bufferzone = f"""
            CREATE TABLE IF NOT EXISTS {boundary_core_table_name} AS
            SELECT ST_Subdivide(ST_Multi(ST_Buffer(geom, -{total_shrink})), 255) AS geom
            FROM {boundary_table_name};
        """
        cursor.execute(sql_bufferzone)

        sql_idx = f"CREATE INDEX IF NOT EXISTS {boundary_core_table_name}_idx ON {boundary_core_table_name} USING GIST (geom);"
        cursor.execute(sql_idx)

    for layer_def in do_layers(params):
        log.debug("Started gap check for the layer %s.", layer_def["pg_layer_name"])

        # Prepare support data
        partitioned_layer = PartitionedLayer(
            params["connection_manager"].get_connection(), layer_def["pg_layer_name"], layer_def["pg_fid_name"]
        )
        gap_table = GapTable(
            partitioned_layer, params["layer_defs"]["boundary"]["pg_layer_name"], params["du_column_name"], use_snapping=False
        )
        gap_table.make()

        sql_params = {
            "gap_table": gap_table.gap_table_name,
            "boundary_core_table": boundary_core_table_name,
            "gap_bufferzone_large_exception_table": f"s{params['step_nr']:02d}_{layer_def['pg_layer_name']}_gap_bufferzone_large_exception",
            "gap_bufferzone_small_exception_table": f"s{params['step_nr']:02d}_{layer_def['pg_layer_name']}_gap_bufferzone_small_exception",
            "gap_interior_small_exception_table": f"s{params['step_nr']:02d}_{layer_def['pg_layer_name']}_gap_interior_small_exception",
            "gap_error_table": f"s{params['step_nr']:02d}_{layer_def['pg_layer_name']}_gap_error",
            "gap_area_tolerance": str(gap_area_tolerance),
            "gap_negative_buffer": str(gap_negative_buffer),
        }

        # Spatial conditions
        # LARGE GAP: Area > AreaTol AND Width > WidthTol (Buffer Area > 0)
        cond_large_gap = f"""
            ST_Area(g.geom) > {gap_area_tolerance} 
            AND ST_Area(ST_Buffer(g.geom, {gap_negative_buffer})) > 0
        """

        # SMALL GAP: Area <= AreaTol OR Width <= WidthTol (Buffer Area = 0)
        cond_small_gap = f"""
            (ST_Area(g.geom) <= {gap_area_tolerance} 
             OR ST_Area(ST_Buffer(g.geom, {gap_negative_buffer})) = 0)
        """

        with params["connection_manager"].get_connection().cursor() as cursor:
            # -------------------------------------------------------------
            # Category 1 & 2: Boundary Zone Gaps (Large & Small Exceptions)
            # -------------------------------------------------------------
            # Boundary Zone = Does NOT intersect the core zone (c.geom IS NULL)
            
            # Boundary Large Exception
            sql_b_large = f"""
                CREATE TABLE {{gap_bufferzone_large_exception_table}} AS
                SELECT ROW_NUMBER() OVER () AS id, g.geom, ST_Area(g.geom) AS area
                FROM {{gap_table}} g
                LEFT JOIN {{boundary_core_table}} c ON ST_Intersects(g.geom, c.geom)
                WHERE c.geom IS NULL AND ({cond_large_gap});
            """.format(**sql_params)
            cursor.execute(sql_b_large)
            if cursor.rowcount > 0:
                status.info(f"Layer {layer_def['pg_layer_name']} has {cursor.rowcount} boundary buffer zone large gap exceptions.")
                status.add_full_table(sql_params["gap_bufferzone_large_exception_table"])

            # Boundary Small Exception
            sql_b_small = f"""
                CREATE TABLE {{gap_bufferzone_small_exception_table}} AS
                SELECT ROW_NUMBER() OVER () AS id, g.geom, ST_Area(g.geom) AS area
                FROM {{gap_table}} g
                LEFT JOIN {{boundary_core_table}} c ON ST_Intersects(g.geom, c.geom)
                WHERE c.geom IS NULL AND ({cond_small_gap});
            """.format(**sql_params)
            cursor.execute(sql_b_small)
            if cursor.rowcount > 0:
                status.info(f"Layer {layer_def['pg_layer_name']} has {cursor.rowcount} boundary buffer zone small gap exceptions.")
                status.add_full_table(sql_params["gap_bufferzone_small_exception_table"])

            # -------------------------------------------------------------
            # Category 3: Interior Large Gaps (REAL ERRORS)
            # -------------------------------------------------------------
            # Interior Zone = Intersects core zone (c.geom IS NOT NULL) AND Large
            sql_errors = f"""
                CREATE TABLE {{gap_error_table}} AS
                SELECT DISTINCT ROW_NUMBER() OVER () AS id, g.geom, ST_Area(g.geom) AS area
                FROM {{gap_table}} g
                INNER JOIN {{boundary_core_table}} c ON ST_Intersects(g.geom, c.geom)
                WHERE {cond_large_gap};
            """.format(**sql_params)
            cursor.execute(sql_errors)
            if cursor.rowcount > 0:
                status.failed(f"Layer {layer_def['pg_layer_name']} has {cursor.rowcount} interior large gaps (errors).")
                status.add_full_table(sql_params["gap_error_table"])

            # -------------------------------------------------------------
            # Category 4: Interior Small Gaps (Exceptions)
            # -------------------------------------------------------------
            # Interior Zone = Intersects core zone (c.geom IS NOT NULL) AND Small
            sql_i_small = f"""
                CREATE TABLE {{gap_interior_small_exception_table}} AS
                SELECT DISTINCT ROW_NUMBER() OVER () AS id, g.geom, ST_Area(g.geom) AS area
                FROM {{gap_table}} g
                INNER JOIN {{boundary_core_table}} c ON ST_Intersects(g.geom, c.geom)
                WHERE {cond_small_gap};
            """.format(**sql_params)
            cursor.execute(sql_i_small)
            if cursor.rowcount > 0:
                status.info(f"Layer {layer_def['pg_layer_name']} has {cursor.rowcount} interior small gap exceptions.")
                status.add_full_table(sql_params["gap_interior_small_exception_table"])

        log.info("GAP check for the layer %s has been finished.", layer_def["pg_layer_name"])