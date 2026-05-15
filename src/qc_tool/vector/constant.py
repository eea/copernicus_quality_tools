#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Features have constant values in specific attributes."
IS_SYSTEM = False


def run_check(params, status):
    from qc_tool.vector.helper import do_layers
    from qc_tool.vector.helper import get_failed_items_message

    cursor = params["connection_manager"].get_connection().cursor()
    for layer_def in do_layers(params):
        for constant_key in params["constant_keys"]:
            sql_params = {"fid_name": layer_def["pg_fid_name"],
                          "layer_name": layer_def["pg_layer_name"],
                          "constant_column_name": constant_key,
                          "error_table_name": "s{:02d}_{:s}_{:s}_error".format(params["step_nr"], layer_def["pg_layer_name"], constant_key)}

            sql = (
                "CREATE TABLE {error_table_name} AS\n"
                "WITH target_constant AS (\n"
                "    SELECT {constant_column_name} AS constant_value\n"
                "    FROM {layer_name}\n"
                "    WHERE {constant_column_name} IS NOT NULL\n"
                "    GROUP BY {constant_column_name}\n"
                "    ORDER BY COUNT(*) DESC, {constant_column_name}\n"
                "    LIMIT 1\n"
                ")\n"
                "SELECT layer.{fid_name}\n"
                "FROM {layer_name} AS layer\n"
                "CROSS JOIN target_constant tc\n"
                "WHERE layer.{constant_column_name} IS DISTINCT FROM tc.constant_value;"
            )

            sql = sql.format(**sql_params)
            cursor.execute(sql)
            if cursor.rowcount > 0:
                failed_items_message = get_failed_items_message(
                    cursor, sql_params["error_table_name"], layer_def["pg_fid_name"]
                )
                status.failed(
                    "The column {:s}.{:s} does not have a constant value; "
                    "features with differing {:s}: {:s}.".format(
                        layer_def["pg_layer_name"],
                        unique_key,
                        layer_def["fid_display_name"],
                        failed_items_message
                    )
                )
                status.add_error_table(
                    sql_params["error_table_name"],
                    layer_def["pg_layer_name"],
                    layer_def["pg_fid_name"]
                )

