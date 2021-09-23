#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import logging


DESCRIPTION = "There is no gap in the AOI."
IS_SYSTEM = False
TOLERANCE = 0.01


log = logging.getLogger(__name__)


def run_check(params, status):
    from qc_tool.vector.helper import do_layers
    from qc_tool.vector.helper import GapTable
    from qc_tool.vector.helper import get_failed_items_message
    from qc_tool.vector.helper import PartitionedLayer

    if "boundary" not in params["layer_defs"]:
        status.info("Check cancelled due to boundary not being available.")
        return

    for layer_def in do_layers(params):
        log.debug("Started gap check for the layer {:s}.".format(layer_def["pg_layer_name"]))

        # Prepare support data.
        partitioned_layer = PartitionedLayer(params["connection_manager"].get_connection(),
                                             layer_def["pg_layer_name"],
                                             layer_def["pg_fid_name"])

        # Update boundary with negative tolerance buffer
        boundary_table_name = params["layer_defs"]["boundary"]["pg_layer_name"]
        sql_params = {"boundary_table": boundary_table_name,
                      "tolerance": TOLERANCE}
        with params["connection_manager"].get_connection().cursor() as cursor:
            sql = "UPDATE {boundary_table} SET geom = ST_BUFFER(geom, -{tolerance});"
            sql = sql.format(**sql_params)
            cursor.execute(sql)

        gap_table = GapTable(partitioned_layer,
                             params["layer_defs"]["boundary"]["pg_layer_name"],
                             params["du_column_name"])
        gap_table.make()

        # Prepare parameters used in sql clauses.
        sql_params = {"gap_table": gap_table.gap_table_name,
                      "gap_warning_table": "s{:02d}_{:s}_gap_warning".format(params["step_nr"], layer_def["pg_layer_name"])}
        with params["connection_manager"].get_connection().cursor() as cursor:
            # Create table of warning items.
            sql = ("CREATE TABLE {gap_warning_table} AS\n"
                   "SELECT geom FROM {gap_table};")
            sql = sql.format(**sql_params)
            cursor.execute(sql)

            # Report warning items.
            if cursor.rowcount > 0:
                status.info("Layer {:s} has {:d} gaps.".format(layer_def["pg_layer_name"], cursor.rowcount))
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
                    status.info("Layer {:s} has {:d} feature(s) of unknown boundary unit."
                                .format(layer_def["pg_layer_name"], cursor.rowcount))
                    status.add_error_table(sql_params["du_warning_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

        log.info("MMU check for the layer {:s} has been finished.".format(layer_def["pg_layer_name"]))
