#!/usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "The area of any multipart polygon is greater than MMU."
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
                      "mmu": mmu}

        # Create table of error items: features with an area smaller than MMU.
        sql = ("CREATE TABLE {error_table} AS"
               " SELECT DISTINCT layer.{fid_name}, ST_Area(geom) AS area"
               " FROM {layer_name} AS layer"
               " WHERE ST_Area(geom) < {mmu};")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report error items.
        items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.failed("Layer {:s} has features with an area smaller than MMU with {:s}: {:s}."
                         .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])
