#! /usr/bin/env python3


from qc_tool.wps.helper import do_layers
from qc_tool.wps.helper import get_failed_pairs_message
from qc_tool.wps.registry import register_check_function


SQL = ("CREATE TABLE {0:s} AS"
       "  SELECT ta.{1:s} a_{1:s}, tb.{1:s} b_{1:s}"
       "  FROM {2:s} ta"
       "    INNER JOIN {2:s} tb ON ta.{1:s} < tb.{1:s}"
       "  WHERE"
       "    ta.wkb_geometry && tb.wkb_geometry"
       "    AND ST_Relate(ta.wkb_geometry, tb.wkb_geometry, 'T********');")


@register_check_function(__name__)
def run_check(params, status):
    cursor = params["connection_manager"].get_connection().cursor()
    for layer_def in do_layers(params):
        error_table_name = "v13_{:s}_error".format(layer_def["pg_layer_name"])
        sql = SQL.format(error_table_name, layer_def["pg_fid_name"], layer_def["pg_layer_name"]);

        cursor.execute(sql)
        if cursor.rowcount == 0:
            cursor.execute("DROP TABLE {:s};".format(error_table_name))
        else:
            failed_pairs_message = get_failed_pairs_message(cursor, error_table_name, layer_def["pg_fid_name"])
            status.failed("The layer {:s} has overlapping pairs in rows: {:s}."
                          .format(layer_def["pg_layer_name"], failed_pairs_message))
            status.add_error_table(error_table_name, layer_def["pg_layer_name"], layer_def["pg_fid_name"])
