#! /usr/bin/env python3


from contextlib import closing

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__, "There are no overlapping polygons.")
def run_check(filepath, params):
    error_counts = {}
    for layer_name in params["layer_names"]:
        with closing(params["connection_manager"].get_connection().cursor()) as cursor:
            sql = "SELECT * FROM __v13_overlapping_polygons(%s, %s);"
            cursor.execute(sql, (layer_name, params["ident_colname"],))
            error_count = cursor.fetchone()[0]
            error_counts[layer_name] = error_count

    status_ok = sum(error_counts.values()) == 0
    if status_ok:
        return {"status": "ok"}
    else:
        message_items = ["{:s}:{:d}".format(layer_name, error_counts[layer_name])
                         for layer_name in params["layer_names"]
                         if error_counts.get(layer_name, 0) > 0]
        message = "Layers with overlapping pairs: {:s}.".format(", ".join(message_items))
        return {"status": "failed", "message": message}
