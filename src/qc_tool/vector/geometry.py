#!/usr/bin/env python3
# -*- coding: utf-8 -*-


from qc_tool.wps.helper import do_layers
from qc_tool.wps.helper import get_failed_items_message


def run_check(params, status):
    cursor = params["connection_manager"].get_connection().cursor()

    for layer_def in do_layers(params):
        # Prepare parameters used in sql clauses.
        sql_params = {"fid_name": layer_def["pg_fid_name"],
                      "layer_name": layer_def["pg_layer_name"],
                      "error_table": "v9_{:s}_invalid".format(layer_def["pg_layer_name"]),
                      "detail_table": "v9_{:s}_detail".format(layer_def["pg_layer_name"])}

        # Create table of error items.
        sql = ("CREATE TABLE {error_table} AS"
               " SELECT {fid_name}"
               " FROM {layer_name}"
               " WHERE NOT ST_IsValid(wkb_geometry);")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report items with invalid geometry.
        items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.failed("Layer {:s} has invalid geometry in features with {:s}: {:s}."
                          .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

            # Create table of descriptions of invalid geometries.
            sql = ("CREATE TABLE {detail_table} AS"
                   " SELECT"
                   "  {fid_name},"
                   "  (ST_IsValidDetail(wkb_geometry)).reason AS reason,"
                   "  ST_SetSRID((ST_IsValidDetail(wkb_geometry)).location, ST_SRID(wkb_geometry)) AS location"
                   "  FROM {layer_name}"
                   " WHERE NOT ST_IsValid(wkb_geometry);")
            sql = sql.format(**sql_params)
            cursor.execute(sql)

            # Report table of descriptions.
            status.add_full_table(sql_params["detail_table"])
