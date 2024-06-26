#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Features use specific codes in specific attributes."
IS_SYSTEM = False


def run_check(params, status):
    from qc_tool.vector.helper import do_layers
    from qc_tool.vector.helper import get_failed_items_message

    # Check if the current delivery is excluded from vector checks
    if "skip_vector_checks" in params:
        if params["skip_vector_checks"]:
            status.info("The delivery has been excluded from vector.enum check because the vector data source does not contain a single object of interest.")
            return

    cursor = params["connection_manager"].get_connection().cursor()
    for layer_def in do_layers(params):
        for column_name, allowed_codes in params["column_defs"]:

            # Prepare clause excluding features with non-null value of specific column.
            if "exclude_column_name" in params:
                exclude_clause = "AND {:s} IS NULL".format(params["exclude_column_name"])
            else:
                exclude_clause = ""

            # Prepare parameters used in sql clauses.
            sql_params = {"fid_name": layer_def["pg_fid_name"],
                          "layer_name": layer_def["pg_layer_name"],
                          "column_name": column_name,
                          "exclude_clause": exclude_clause,
                          "error_table": "s{:02d}_{:s}_{:s}_error".format(params["step_nr"], layer_def["pg_layer_name"], column_name)}

            # Create table of error items.
            sql = ("CREATE TABLE {error_table} AS"
                   " SELECT {fid_name}"
                   " FROM {layer_name}"
                   " WHERE"
                   "  ({column_name} IS NULL"
                   "   OR {column_name} NOT IN %s)"
                   "  {exclude_clause};")
            sql = sql.format(**sql_params)
            cursor.execute(sql, [tuple(allowed_codes)])

            # Report error items.
            items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
            if items_message is not None:
                status.failed("Layer {:s} has column {:s} with invalid codes in features with {:s}: {:s}."
                              .format(layer_def["pg_layer_name"], column_name, layer_def["fid_display_name"], items_message))
                status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])
