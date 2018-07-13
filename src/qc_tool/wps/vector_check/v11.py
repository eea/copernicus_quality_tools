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
        error_table_name = "{:s}_lessmmu_error".format(layer_name)
        except_table_name = "{:s}_lessmmu_except".format(layer_name)
        cursor.execute("SELECT __V11_mmu_status(%s, %s, %s);", (area_m, layer_name, border_exception))
        cursor.execute("SELECT DISTINCT {0:s} FROM {1:s} ORDER BY {0:s};".format(params["ident_colname"], error_table_name))
        if cursor.rowcount == 0:
            cursor.execute("DROP TABLE {:s};".format(error_table_name))
        else:
            failed_ids = [row[0] for row in cursor.fetchmany(FAILED_ITEMS_LIMIT)]
            failed_ids_message = shorten_failed_items_message(failed_ids, cursor.rowcount)
            if border_exception:
                failed_message = "The layer {:s} has polygons with area less then MMU in rows: {:s}.".format(layer_name, failed_ids_message)
            else:
                failed_message = "The layer {:s} has non-bordering polygons with area less then MMU in rows: {:s}.".format(layer_name, failed_ids_message)
            status.add_message(failed_message)
            status.add_error_table(error_table_name)

        if border_exception:
            cursor.execute("SELECT DISTINCT {0:s} FROM {1:s} ORDER BY {0:s};".format(params["ident_colname"], except_table_name))
            if cursor.rowcount == 0:
                cursor.execute("DROP TABLE {:s};".format(except_table_name))
            else:
                failed_ids = [row[0] for row in cursor.fetchmany(FAILED_ITEMS_LIMIT)]
                failed_ids_message = shorten_failed_items_message(failed_ids, cursor.rowcount)
                failed_message = "The layer {:s} has bordering polygons with area less then MMU in rows: {:s}.".format(layer_name, failed_ids_message)
                status.add_message(failed_message)
                status.add_error_table(error_table_name)
