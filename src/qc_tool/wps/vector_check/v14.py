#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import re

from qc_tool.wps.helper import do_layers
from qc_tool.wps.helper import get_failed_pairs_message
from qc_tool.wps.registry import register_check_function


def create_all_breaking_neighbcode(cursor, pg_fid_name, pg_layer_name, error_table_name, code_colnames, exclude_codes):
    pair_clause = " AND ".join("ta.{0:s} = tb.{0:s}".format(code_colname) for code_colname in code_colnames)
    exclude_clause = " AND ".join("ta.{0:s} NOT LIKE '{1:s}'".format(code_colname, exclude_code)
                                  for code_colname in code_colnames
                                  for exclude_code in exclude_codes)
    if len(exclude_clause) > 0:
        exclude_clause = " AND " + exclude_clause
    sql = ("CREATE TABLE {0:s} AS"
           "  SELECT ta.{1:s} a_{1:s}, tb.{1:s} b_{1:s}"
           "  FROM {2:s} ta"
           "    INNER JOIN {2:s} tb ON ta.{1:s} < tb.{1:s}"
           "  WHERE"
           "    {3:s}"
           "    {4:s}"
           "    AND ta.wkb_geometry && tb.wkb_geometry"
           "    AND ST_Dimension(ST_Intersection(ta.wkb_geometry, tb.wkb_geometry)) >= 1;")
    sql = sql.format(error_table_name, pg_fid_name, pg_layer_name, pair_clause, exclude_clause)
    cursor.execute(sql)
    return cursor.rowcount


@register_check_function(__name__)
def run_check(params, status):
    cursor = params["connection_manager"].get_connection().cursor()

    for layer_def in do_layers(params):
        if "code_regex" in params:
            mobj = re.search(params["code_regex"], layer_def["pg_layer_name"])
            code = mobj.group(1)
            code_colnames = params["code_to_column_names"][code]
        else:
            code_colnames = params["code_colnames"]
        exclude_codes = params.get("exclude_codes", [])

        error_table_name = "{:s}_neighbcode_error".format(layer_def["pg_layer_name"])
        error_count = create_all_breaking_neighbcode(cursor, layer_def["pg_fid_name"], layer_def["pg_layer_name"], error_table_name, code_colnames, exclude_codes)
        if error_count == 0:
            cursor.execute("DROP TABLE {:s};".format(error_table_name))
        else:
            failed_pairs_message = get_failed_pairs_message(cursor, error_table_name, layer_def["pg_fid_name"])
            failed_message = "The layer {:s} has neighbouring polygons with the same codes in rows: {:s}.".format(layer_def["pg_layer_name"], failed_pairs_message)
            status.add_message(failed_message)
            status.add_error_table(error_table_name, layer_def["pg_layer_name"], layer_def["pg_fid_name"])
