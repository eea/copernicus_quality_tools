#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Unique identifier check.
"""


from qc_tool.common import FAILED_ITEMS_LIMIT
from qc_tool.wps.helper import shorten_failed_items_message
from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    """
    Unique identifier check.
    :param params: configuration
    :return: status + message
    """
    cursor = params["connection_manager"].get_connection().cursor()
    for layer_name in params["layer_names"]:
        # create table of valid code errors
        cursor.execute("""SELECT __V5_UniqueID('{0}','{1}');""".format(layer_name, params["product_code"]))

        # get wrong UniqueID ids and count. the _uniqueid_error table was created by the __V5_UniqueID function.
        cursor.execute("""SELECT {0} FROM {1}_uniqueid_error;""".format(params["ident_colname"], layer_name))
        failed_ids = [row[0] for row in cursor.fetchmany(FAILED_ITEMS_LIMIT)]
        if len(failed_ids) > 0:
            failed_ids_message = shorten_failed_items_message(failed_ids, cursor.rowcount)
            failed_message = "The layer {:s} has non-unique identifiers: {:s}.".format(layer_name, failed_ids_message)
            status.add_message(failed_message)

        # drop temporary table with code errors
        cursor.execute("""DROP TABLE {:s}_uniqueid_error;""".format(layer_name))
