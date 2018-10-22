#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import re

from qc_tool.wps.helper import do_layers
from qc_tool.wps.helper import dump_failed_items
from qc_tool.wps.helper import get_failed_items_message
from qc_tool.wps.registry import register_check_function


SQL = ("CREATE TABLE {0:s} AS"
       "  SELECT {1:s}"
       "  FROM {2:s}"
       "  WHERE"
       "    {3:s} IS NULL"
       "    OR {3:s} NOT IN %s;")


@register_check_function(__name__)
def run_check(params, status):
    cursor = params["connection_manager"].get_connection().cursor()
    for layer_def in do_layers(params):
        if "code_regex" in params:
            mobj = re.search(params["code_regex"], layer_def["pg_layer_name"])
            code = mobj.group(1)
            column_defs = params["code_to_column_defs"][code]
        else:
            column_defs = params["column_defs"]

        for column_name, value_set_name in column_defs:
            error_table_name = "{:s}_{:s}_validcodes_error".format(layer_def["pg_layer_name"], column_name)
            sql = SQL.format(error_table_name,
                             layer_def["pg_fid_name"],
                             layer_def["pg_layer_name"],
                             column_name)

            # allowed_codes are retrieved from _check_defaults v6 "codes" global parameter.
            allowed_codes = tuple(params["codes"][value_set_name],)

            cursor.execute(sql, (allowed_codes,))
            if cursor.rowcount == 0:

                cursor.execute("DROP TABLE {:s};".format(error_table_name))
            else:
                failed_items_message = get_failed_items_message(cursor, error_table_name, layer_def["pg_fid_name"])
                failed_message = "The layer {:s} has column {:s} with invalid codes in rows: {:s}.".format(layer_def["pg_layer_name"], column_name, failed_items_message)
                status.add_message(failed_message)
                status.add_error_table(error_table_name)
                error_filename = dump_failed_items(params["connection_manager"],
                                                   error_table_name,
                                                   layer_def["pg_fid_name"],
                                                   layer_def["pg_layer_name"],
                                                   params["output_dir"])
                status.add_support_file(error_filename)
