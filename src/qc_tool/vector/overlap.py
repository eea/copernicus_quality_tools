#! /usr/bin/env python3


import logging


DESCRIPTION = "There is no couple of overlapping polygons."
IS_SYSTEM = False


log = logging.getLogger(__name__)


def run_check(params, status):
    from qc_tool.vector.helper import do_layers
    from qc_tool.vector.helper import get_failed_items_message
    from qc_tool.vector.helper import NeighbourTable
    from qc_tool.vector.helper import PartitionedLayer

    cursor = params["connection_manager"].get_connection().cursor()
    for layer_def in do_layers(params):
        log.debug("Started overlap check for the layer {:s}.".format(layer_def["pg_layer_name"]))

        # Prepare support data.
        partitioned_layer = PartitionedLayer(cursor.connection, layer_def["pg_layer_name"], layer_def["pg_fid_name"])
        partitioned_layer.make()
        neighbour_table = NeighbourTable(partitioned_layer)
        neighbour_table.make()

        # Create table of error items.
        sql_params = {"fid_name": layer_def["pg_fid_name"],
                      "neighbour_table": neighbour_table.neighbour_table_name,
                      "error_table": "s{:02d}_{:s}_error".format(params["step_nr"], layer_def["pg_layer_name"])}
        sql = ("CREATE TABLE {error_table} AS\n"
               "SELECT DISTINCT fida AS {fid_name}\n"
               "FROM {neighbour_table}\n"
               "WHERE dim >= 2;")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report error items.
        items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.failed("Layer {:s} has overlapping pairs in features with {:s}: {:s}."
                          .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

        log.info("Overlap check for the layer {:s} has been finished.".format(layer_def["pg_layer_name"]))
