#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import logging


DESCRIPTION = "There is no gap in the AOI."
IS_SYSTEM = False
DEFAULT_BOUNDARY_TOLERANCE = 0.01 # tolerance at the edge of the AOI in metres
DEFAULT_GAP_AREA_TOLERANCE = 0.000001 # square metres
DEFAULT_GAP_WIDTH_TOLERANCE = 0.00001 # square metres


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

    gap_area_tolerance = params.get("gap_area_tolerance", DEFAULT_GAP_AREA_TOLERANCE)
    gap_width_tolerance = params.get("gap_width_tolerance", DEFAULT_GAP_WIDTH_TOLERANCE)

    for layer_def in do_layers(params):
        log.debug("Started gap check for the layer {:s}.".format(layer_def["pg_layer_name"]))

        # Prepare support data.
        partitioned_layer = PartitionedLayer(params["connection_manager"].get_connection(),
                                             layer_def["pg_layer_name"],
                                             layer_def["pg_fid_name"])

        # Update boundary with negative tolerance buffer
        boundary_table_name = params["layer_defs"]["boundary"]["pg_layer_name"]

        sql_params = {"boundary_table": boundary_table_name,
                          "tolerance": boundary_tolerance}
        with params["connection_manager"].get_connection().cursor() as cursor:
            sql = "UPDATE {boundary_table} SET geom = ST_Multi(ST_BUFFER(geom, -{tolerance}));"
            sql = sql.format(**sql_params)
            cursor.execute(sql)

        gap_table = GapTable(partitioned_layer,
                             params["layer_defs"]["boundary"]["pg_layer_name"],
                             params["du_column_name"])
        gap_table.make()

        # Prepare parameters used in sql clauses.
        sql_params = {"gap_table": gap_table.gap_table_name,
                      "gap_exception_table": "s{:02d}_{:s}_gap_exception".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "gap_warning_table": "s{:02d}_{:s}_gap_warning".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "gap_area_tolerance": str(gap_area_tolerance),
                      "gap_width_tolerance": str(gap_width_tolerance)}
        with params["connection_manager"].get_connection().cursor() as cursor:

            # Create table of exception items (if we have high tolerance for gaps).
            if gap_area_tolerance > DEFAULT_GAP_AREA_TOLERANCE or gap_width_tolerance > DEFAULT_GAP_WIDTH_TOLERANCE:
                sql = ("CREATE TABLE {gap_exception_table} AS\n"
                       "SELECT geom FROM {gap_table}\n"
                       "WHERE ST_AREA(geom) <= {gap_area_tolerance}\n"
                       "OR ST_MinimumClearance(geom) <= {gap_width_tolerance}\n"
                       "OR ST_XMAX(geom) - ST_XMIN(geom) <= {gap_width_tolerance}\n"
                       "OR ST_YMAX(geom) - ST_YMIN(geom) <= {gap_width_tolerance};")
                sql = sql.format(**sql_params)
                cursor.execute(sql)
                if cursor.rowcount > 0:
                    # Report exception items.
                    status.info("Layer {:s} has {:d} gap exceptions with area <= {:s} or width <= {:s} tolerance."
                                .format(layer_def["pg_layer_name"], cursor.rowcount,
                                        str(gap_area_tolerance), str(gap_width_tolerance)))
                    # Report gap exception table.
                    status.add_full_table(sql_params["gap_exception_table"])

            # Create table of warning items.
            sql = ("CREATE TABLE {gap_warning_table} AS\n"
                   "SELECT geom FROM {gap_table}\n"
                   "WHERE ST_AREA(geom) > {gap_area_tolerance}\n"
                   "AND ST_MinimumClearance(geom) > {gap_width_tolerance}\n"
                   "AND (\n"
                   "  ST_XMAX(geom) - ST_XMIN(geom) > {gap_width_tolerance}\n"
                   "  AND ST_YMAX(geom) - ST_YMIN(geom) > {gap_width_tolerance}\n"
                   ");")
            sql = sql.format(**sql_params)
            cursor.execute(sql)

            # Report warning items.
            if cursor.rowcount > 0:
                status.failed("Layer {:s} has {:d} gaps.".format(layer_def["pg_layer_name"], cursor.rowcount))
                status.add_full_table(sql_params["gap_warning_table"])

        if params["du_column_name"] is not None:
            sql_params = {"fid_column": layer_def["pg_fid_name"],
                          "layer_table": layer_def["pg_layer_name"],
                          "du_column": params["du_column_name"],
                          "boundary_table": params["layer_defs"]["boundary"]["pg_layer_name"],
                          "du_warning_table": "s{:02d}_{:s}_du_warning".format(params["step_nr"], layer_def["pg_layer_name"])}
            # Create table of excessive items.
            sql = ("CREATE TABLE {du_warning_table} AS\n"
                   "SELECT layer.{fid_column}\n"
                   "FROM\n"
                   " {layer_table} AS layer\n"
                   " LEFT JOIN (SELECT DISTINCT {du_column} FROM {boundary_table}) AS dut ON layer.{du_column} = dut.{du_column}\n"
                   "WHERE\n"
                   " dut.{du_column} IS NULL;")
            with params["connection_manager"].get_connection().cursor() as cursor:
                sql = sql.format(**sql_params)
                cursor.execute(sql)

                # Report excessive items.
                if cursor.rowcount > 0:
                    status.failed("Layer {:s} has {:d} feature(s) of unknown boundary unit."
                                .format(layer_def["pg_layer_name"], cursor.rowcount))
                    status.add_error_table(sql_params["du_warning_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

        log.info("MMU check for the layer {:s} has been finished.".format(layer_def["pg_layer_name"]))
