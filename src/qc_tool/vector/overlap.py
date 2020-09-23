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
        neighbour_table = NeighbourTable(partitioned_layer)
        neighbour_table.make()

        # Create table of error items.
        sql_params = {"fid_name": layer_def["pg_fid_name"],
                      "feature_table": layer_def["pg_layer_name"],
                      "neighbour_table": neighbour_table.neighbour_table_name,
                      "error_table": "s{:02d}_{:s}_error".format(params["step_nr"], layer_def["pg_layer_name"])}
        sql = ("CREATE TABLE {error_table} AS\n"
               "SELECT DISTINCT a.fid AS {fid_name}\n"
               "FROM\n"
               " (SELECT {fid_name} AS fid, geom FROM {feature_table}\n"
               "   WHERE {fid_name} in (SELECT fida from {neighbour_table} WHERE dim > 1)) AS a,\n"
               " (SELECT {fid_name} AS fid, geom FROM {feature_table}\n"
               "   WHERE {fid_name} in (SELECT fidb from {neighbour_table} WHERE dim > 1)) AS b\n"
               "WHERE a.fid <> b.fid AND ST_Dimension(ST_Intersection(a.geom, b.geom)) >= 2\n")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report error items.
        items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
        if items_message is not None:

            # If there are error items are found, then add a full table with intersection areas.
            sql = ("CREATE TABLE {overlap_detail_table} AS\n"
               "SELECT DISTINCT a.fid AS fida, b.fid as fidb, polygon_dump(ST_Intersection(a.geom, b.geom)) as geom\n"
               "FROM\n"
               " (SELECT {fid_name} AS fid, geom FROM {feature_table}\n"
               "   WHERE {fid_name} in (SELECT fida from {neighbour_table} WHERE dim > 1)) AS a,\n"
               " (SELECT {fid_name} AS fid, geom FROM {feature_table} "
               "   WHERE {fid_name} in (SELECT fidb from {neighbour_table} WHERE dim > 1)) AS b\n"
               "WHERE a.fid > b.fid AND ST_Dimension(ST_Intersection(a.geom, b.geom)) >= 2\n")
            sql_params["overlap_detail_table"] = "s{:02d}_{:s}_detail".format(params["step_nr"], layer_def["pg_layer_name"])
            sql = sql.format(**sql_params)
            cursor.execute(sql)
            status.add_full_table(sql_params["overlap_detail_table"])

            status.failed("Layer {:s} has overlapping pairs in features with {:s}: {:s}."
                          .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

        log.info("Overlap check for the layer {:s} has been finished.".format(layer_def["pg_layer_name"]))
