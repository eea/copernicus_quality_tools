#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Detects non-probable changes."
IS_SYSTEM = False


NON_PROBABLE_CHANGES_TABLE_NAME = "non_probable"


def run_check(params, status):
    import osgeo.ogr as ogr
    import osgeo.osr as osr

    from qc_tool.vector.helper import do_layers
    from qc_tool.vector.helper import get_failed_items_message

    cursor = params["connection_manager"].get_connection().cursor()
    sql_params = {"changes_table": NON_PROBABLE_CHANGES_TABLE_NAME}
    
    # Load non-probable changes.
    sql = "DROP TABLE IF EXISTS {changes_table};"
    sql = sql.format(**sql_params)
    cursor.execute(sql)

    sql = "CREATE TABLE {changes_table} (initial_code varchar, final_code varchar);"
    sql = sql.format(**sql_params)
    cursor.execute(sql)

    for initial_code, final_codes in params["changes"]:
        for final_code in final_codes:
            sql = "INSERT INTO {changes_table} VALUES (%s, %s);"
            sql = sql.format(**sql_params)
            cursor.execute(sql, [initial_code, final_code])

    sql = "CREATE INDEX {changes_table}_idx ON {changes_table} (initial_code, final_code);"
    sql = sql.format(**sql_params)
    cursor.execute(sql)

    for layer_def in do_layers(params):
        # Prepare parameters used in sql clauses.
        sql_params.update({"fid_name": layer_def["pg_fid_name"],
                           "layer_name": layer_def["pg_layer_name"],
                           "initial_code_column_name": params["initial_code_column_name"],
                           "final_code_column_name": params["final_code_column_name"],
                           "warning_table": "s{:02d}_{:s}_warning".format(params["step_nr"], layer_def["pg_layer_name"])})

        # Create warning table.
        sql = ("CREATE TABLE {warning_table} AS"
               " SELECT {fid_name}"
               " FROM {layer_name}"
               " WHERE"
               "  ({initial_code_column_name}, {final_code_column_name}) IN (SELECT initial_code, final_code FROM {changes_table});")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report warning items.
        items_message = get_failed_items_message(cursor, sql_params["warning_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.info("Layer {:s} has warning features with {:s}: {:s}."
                        .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["warning_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

