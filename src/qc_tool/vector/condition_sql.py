#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import logging
import re


DESCRIPTION = "Column value does not violate SQL condition"
IS_SYSTEM = False


log = logging.getLogger(__name__)



def run_check(params, status):
    from qc_tool.vector.helper import do_layers
    from qc_tool.vector.helper import get_failed_items_message

    cursor = params["connection_manager"].get_connection().cursor()

    for layer_def in do_layers(params):
        log.debug("Started condition check for the layer {:s}.".format(layer_def["pg_layer_name"]))
        conditions = params["error_wheres"]
        for condition_no, error_where in enumerate(conditions):
            log.debug("Started condition check for  {:s}.".format(error_where))

            # Prepare parameters used in sql clauses.
            sql_params = {"layer_name": layer_def["pg_layer_name"],
                          "fid_name": layer_def["pg_fid_name"],
                          "error_where": error_where}

            # Create table of error items.
            error_table = "s{:02d}_{:s}_condition_{:02d}_error".format(params["step_nr"], layer_def["pg_layer_name"], condition_no + 1)
            sql = ("CREATE TABLE {error_table} ({fid_name} integer PRIMARY KEY);")
            sql = sql.format(error_table=error_table, **sql_params)
            cursor.execute(sql)
            sql = ("INSERT INTO {error_table}\n"
                   "SELECT {fid_name}\n"
                   "FROM {layer_name}\n"
                   "WHERE  ({error_where});")
            sql = sql.format(error_table=error_table, **sql_params)
            cursor.execute(sql)
            log.info("Error table {:s} has been inserted {:d} items.".format(error_table, cursor.rowcount))

            # Report error items.
            items_message = get_failed_items_message(cursor, error_table, layer_def["pg_fid_name"])
            if items_message is not None:
                status.failed("Layer {:s} violates the condition  '{:s}' in rows: {:s}."
                            .format(layer_def["pg_layer_name"], error_where, items_message))
                status.add_error_table(error_table, layer_def["pg_layer_name"], layer_def["pg_fid_name"])

        log.info("Condition check for the layer {:s} has been finished.".format(layer_def["pg_layer_name"]))
