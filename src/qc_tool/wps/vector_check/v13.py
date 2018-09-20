#! /usr/bin/env python3


from qc_tool.wps.helper import get_failed_pairs_message
from qc_tool.wps.registry import register_check_function


SQL = ("CREATE TABLE {0:s} AS"
       "  SELECT ta.{1:s} a_{1:s}, tb.{1:s} b_{1:s}"
       "  FROM {2:s} ta INNER JOIN {2:s} tb ON ta.{1:s} < tb.{1:s}"
       "  WHERE ST_Relate(ta.wkb_geometry, tb.wkb_geometry, 'T********');")


@register_check_function(__name__)
def run_check(params, status):
    cursor = params["connection_manager"].get_connection().cursor()
    for layer_name in params["db_layer_names"]:
        error_table_name = "{:s}_overlap_error".format(layer_name)
        sql = SQL.format(error_table_name, params["fid_column_name"], layer_name);
        cursor.execute(sql)
        if cursor.rowcount == 0:
            cursor.execute("DROP TABLE {:s};".format(error_table_name))
        else:
            failed_pairs_message = get_failed_pairs_message(cursor, error_table_name, params["fid_column_name"])
            failed_message = "The layer {:s} has overlapping pairs in rows: {:s}.".format(layer_name, failed_pairs_message)
            status.add_message(failed_message)
            status.add_error_table(error_table_name)
