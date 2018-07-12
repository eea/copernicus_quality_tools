#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from qc_tool.common import FAILED_ITEMS_LIMIT
from qc_tool.wps.helper import shorten_failed_items_message
from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    cursor = params["connection_manager"].get_connection().cursor()
    for layer_name in params["db_layer_names"]:
        cursor.execute("SELECT __V14_NeighbCodes(%s, %s);", (layer_name, params["product_code"]))
        cursor.execute("SELECT {:s} FROM {:s}_neighbcode_error;".format(params["ident_colname"], layer_name))
        failed_ids = [row[0] for row in cursor.fetchmany(FAILED_ITEMS_LIMIT)]
        if len(failed_ids) > 0:
            failed_ids_message = shorten_failed_items_message(failed_ids, cursor.rowcount)
            failed_message = "The layer {:s} has polygons with the same code as its neighbour: {:s}.".format(layer_name, failed_ids_message)
            status.add_message(failed_message)
            status.add_error_table("{:s}_neighbcode_error".format(layer_name))
