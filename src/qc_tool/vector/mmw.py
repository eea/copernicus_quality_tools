#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import re

from qc_tool.wps.helper import do_layers
from qc_tool.wps.helper import get_failed_items_message


DESCRIPTION = "Minimum mapping width."
IS_SYSTEM = False


def run_check(params, status):
    cursor = params["connection_manager"].get_connection().cursor()

    for layer_def in do_layers(params):
        # Prepare parameters used in sql clauses.
        sql_params = {"fid_name": layer_def["pg_fid_name"],
                      "layer_name": layer_def["pg_layer_name"],
                      "warning_table": "v12_{:s}_warning".format(layer_def["pg_layer_name"])}

        # Create table of warning items.
        sql = ("CREATE TABLE {warning_table} AS"
               " SELECT {layer_name}.{fid_name}"
               " FROM {layer_name}"
               " WHERE ST_NumGeometries(ST_Buffer(wkb_geometry, %s)) <> 1;")
        sql = sql.format(**sql_params)
        cursor.execute(sql, [-params["mmw"]])

        # Report warning features.
        items_message = get_failed_items_message(cursor, sql_params["warning_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.info("Layer {:s} has warning features with {:s}: {:s}."
                        .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["warning_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])
