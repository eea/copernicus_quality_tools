#! /usr/bin/env python3


from contextlib import closing

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    for layer_name in params["layer_names"]:
        cursor = params["connection_manager"].get_connection().cursor()
        sql = "SELECT * FROM __v13_overlapping_polygons(%s, %s);"
        cursor.execute(sql, [layer_name, params["ident_colname"]])
        error_count = cursor.fetchone()[0]
        if error_count > 0:
            status.add_message("Layer {:s} has {:d} overlapping pairs.".format(layer_name, error_count))
