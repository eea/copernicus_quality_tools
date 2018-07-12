#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from qc_tool.common import FAILED_ITEMS_LIMIT
from qc_tool.wps.helper import shorten_failed_items_message
from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    border_exception = params["border_exception"]
    area_m = int(params["area_ha"]) * 10000

    cursor = params["connection_manager"].get_connection().cursor()

    for layer_name in params["db_layer_names"]:
        cursor.execute("SELECT __v11_mmu_status(%s, %s, %s);", (area_m, layer_name, border_exception))
        cursor.execute("SELECT {:s} FROM {:s}_lessmmu_error;".format(params["ident_colname"], layer_name))
        failed_ids = [row[0] for row in cursor.fetchmany(FAILED_ITEMS_LIMIT)]
        if len(failed_ids) > 0:
            failed_ids_message = shorten_failed_items_message(failed_ids, cursor.rowcount)
            status.add_message("Layer {:s} has polygons under MMU: {:s}.".format(layer_names, failed_ids_message))
            status.add_error_table("{:s}_lessmmu_error".format(layer_name))
            if border_exception:
                status.add_error_table("{:s}_lessmmu_except".format(layer_name))
