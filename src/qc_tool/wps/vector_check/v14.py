#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import re

from qc_tool.wps.helper import get_failed_pairs_message
from qc_tool.wps.registry import register_check_function


def create_all_breaking_neighbcode(cursor, fid_column_name, layer_name, error_table_name, code_colnames):
    sql = ("CREATE TABLE {0:s} AS"
           "  SELECT ta.{1:s} a_{1:s}, tb.{1:s} b_{1:s}"
           "  FROM {2:s} ta"
           "    INNER JOIN {2:s} tb ON ta.{1:s} < tb.{1:s}"
           "  WHERE"
           "    {3:s}"
           "    AND ta.wkb_geometry && tb.wkb_geometry"
           "    AND ST_Relate(ta.wkb_geometry, tb.wkb_geometry, '*T*******');")
    code_where = " AND ".join("ta.{0:s} = tb.{0:s}".format(code_colname) for code_colname in code_colnames)
    sql = sql.format(error_table_name, fid_column_name, layer_name, code_where)
    cursor.execute(sql)
    return cursor.rowcount


@register_check_function(__name__)
def run_check(params, status):
    cursor = params["connection_manager"].get_connection().cursor()
    for layer_name in params["db_layer_names"]:
        if "code_regex" in params:
            mobj = re.search(params["code_regex"], layer_name)
            code = mobj.group(1)
            code_colnames = params["code_to_column_names"][code]
        else:
            code_colnames = params["code_colnames"]

        error_table_name = "{:s}_neighbcode_error".format(layer_name)
        error_count = create_all_breaking_neighbcode(cursor, params["fid_column_name"], layer_name, error_table_name, code_colnames)
        if error_count == 0:
            cursor.execute("DROP TABLE {:s};".format(error_table_name))
        else:
            failed_pairs_message = get_failed_pairs_message(cursor, error_table_name, params["fid_column_name"])
            failed_message = "The layer {:s} has neighbouring polygons with the same codes in rows: {:s}.".format(layer_name, failed_pairs_message)
            status.add_message(failed_message)
            status.add_error_table(error_table_name)
