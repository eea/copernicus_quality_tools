#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import logging


DESCRIPTION = "There is no couple of neighbouring polygons having the same code."
IS_SYSTEM = False


log = logging.getLogger(__name__)


def run_check(params, status):
    from qc_tool.vector.helper import create_pg_has_comment
    from qc_tool.vector.helper import do_layers
    from qc_tool.vector.helper import get_failed_items_message
    from qc_tool.vector.helper import NeighbourTable
    from qc_tool.vector.helper import PartitionedLayer

    # Check if the current delivery is excluded from vector checks
    if "skip_vector_checks" in params:
        if params["skip_vector_checks"]:
            status.info("The delivery has been excluded from vector.neighbour check because the vector data source does not contain a single object of interest.")
            return

    cursor = params["connection_manager"].get_connection().cursor()
    for layer_def in do_layers(params):
        log.debug("Started neighbour check for the layer {:s}.".format(layer_def["pg_layer_name"]))

        # Prepare support data.
        partitioned_layer = PartitionedLayer(cursor.connection, layer_def["pg_layer_name"], layer_def["pg_fid_name"])
        neighbour_table = NeighbourTable(partitioned_layer)
        neighbour_table.make()
        create_pg_has_comment(cursor.connection)

        # Prepare parameters for sql query.
        sql_params = {"fid_name": layer_def["pg_fid_name"],
                      "layer_name": layer_def["pg_layer_name"],
                      "neighbour_table": neighbour_table.neighbour_table_name,
                      "exception_table": "s{:02d}_{:s}_exception".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "exception_pairs_table": "s{:02d}_{:s}_exception_pairs".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "error_table": "s{:02d}_{:s}_error".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "error_pairs_table": "s{:02d}_{:s}_error_pairs".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "pair_clause": " AND ".join("layer.{0:s} = other.{0:s}".format(code_column_name)
                                                  for code_column_name in params["code_column_names"]),
                      "exception_where": "\n".join(params["exception_where"]),
                      "error_where": "\n".join(params["error_where"])}

        # Create exception pairs table.
        sql = ("CREATE TABLE {exception_pairs_table} AS\n"
               "SELECT layer.{fid_name} AS fida, other.{fid_name} AS fidb\n"
               "FROM\n"
               " {layer_name} AS layer\n"
               " INNER JOIN {neighbour_table} AS neib ON layer.{fid_name} = neib.fida\n"
               " INNER JOIN {layer_name} AS other ON neib.fidb = other.{fid_name}\n"
               "WHERE\n"
               " ({exception_where})\n"
               " AND ({pair_clause});")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Create error pairs table.
        sql = ("CREATE TABLE {error_pairs_table} AS\n"
               "SELECT layer.{fid_name} AS fida, other.{fid_name} AS fidb\n"
               "FROM\n"
               " {layer_name} AS layer\n"
               " INNER JOIN {neighbour_table} AS neib ON layer.{fid_name} = neib.fida\n"
               " INNER JOIN {layer_name} AS other ON neib.fidb = other.{fid_name}\n"
               " LEFT JOIN {exception_pairs_table} AS excp ON layer.{fid_name} = excp.fida AND other.{fid_name} = excp.fidb\n"
               "WHERE\n"
               " excp.fida IS NULL\n"
               " AND ({error_where})\n"
               " AND ({pair_clause});")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Create exception table.
        sql = ("CREATE TABLE {exception_table} AS\n"
               "SELECT DISTINCT unnest(ARRAY[fida, fidb]) AS {fid_name}\n"
               "FROM {exception_pairs_table};")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report exception items.
        items_message = get_failed_items_message(cursor, sql_params["exception_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.info("Layer {:s} has exception features with {:s}: {:s}."
                        .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["exception_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

        # Create error table.
        sql = ("CREATE TABLE {error_table} AS\n"
               "SELECT DISTINCT unnest(ARRAY[fida, fidb]) AS {fid_name}\n"
               "FROM {error_pairs_table};")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report error items.
        items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.failed("Layer {:s} has error features with {:s}: {:s}."
                          .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

        log.info("Neighbour check for the layer {:s} has been finished.".format(layer_def["pg_layer_name"]))
