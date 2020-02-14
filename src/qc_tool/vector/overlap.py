#! /usr/bin/env python3


DESCRIPTION = "There is no couple of overlapping polygons."
IS_SYSTEM = False


def run_check(params, status):
    from qc_tool.vector.helper import do_layers
    from qc_tool.vector.helper import get_failed_items_message

    cursor = params["connection_manager"].get_connection().cursor()
    for layer_def in do_layers(params):
        # Prepare parameters used in sql clauses.
        sql_params = {"fid_name": layer_def["pg_fid_name"],
                      "layer_name": layer_def["pg_layer_name"],
                      "error_table": "s{:02d}_{:s}_error".format(params["step_nr"], layer_def["pg_layer_name"])}

        # Prepare exclude clause.
        exclude_column_name = params.get("exclude_column_name", None)
        if exclude_column_name is None:
            sql_params["exclude_clause"] = "TRUE"
            sql_execute_params = {}
        else:
            exclude_clause = ("{exclude_column_name} IS NULL OR {exclude_column_name} NOT IN %(exclude_codes)s ")
            sql_params["exclude_clause"] = exclude_clause.format(exclude_column_name=exclude_column_name)
            sql_execute_params = {"exclude_codes": tuple(params["exclude_codes"])}

        # Create table of error items.
        sql = ("CREATE TABLE {error_table} AS"
               "  SELECT DISTINCT unnest(ARRAY[ta.{fid_name}, tb.{fid_name}]) AS {fid_name}"
               "  FROM"
               "  (SELECT * FROM {layer_name} WHERE {exclude_clause}) AS ta,"
               "  (SELECT * FROM {layer_name} WHERE {exclude_clause}) AS tb"
               "  WHERE ta.{fid_name} < tb.{fid_name}"
               "    AND ta.geom && tb.geom"
               "    AND ST_Relate(ta.geom, tb.geom, 'T********');")
        sql = sql.format(**sql_params)
        cursor.execute(sql, sql_execute_params)

        # Report error items.
        items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.failed("Layer {:s} has overlapping pairs in features with {:s}: {:s}."
                          .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])
