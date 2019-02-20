#! /usr/bin/env python3


from qc_tool.vector.helper import do_layers
from qc_tool.vector.helper import get_failed_items_message


DESCRIPTION = "There is no couple of overlapping polygons."
IS_SYSTEM = False


def run_check(params, status):
    cursor = params["connection_manager"].get_connection().cursor()
    for layer_def in do_layers(params):
        # Prepare parameters used in sql clauses.
        sql_params = {"fid_name": layer_def["pg_fid_name"],
                      "layer_name": layer_def["pg_layer_name"],
                      "error_table": "v13_{:s}_error".format(layer_def["pg_layer_name"])}

        # Create table of error items.
        sql = ("CREATE TABLE {error_table} AS"
               "  SELECT DISTINCT ta.{fid_name} AS {fid_name}"
               "  FROM {layer_name} ta, {layer_name} tb"
               "  WHERE"
               "    ta.{fid_name} <> tb.{fid_name}"
               "    AND ta.wkb_geometry && tb.wkb_geometry"
               "    AND ST_Relate(ta.wkb_geometry, tb.wkb_geometry, 'T********');")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report error items.
        items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.failed("Layer {:s} has overlapping pairs in features with {:s}: {:s}."
                          .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])
