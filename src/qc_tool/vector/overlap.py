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

    # Check if the current delivery is excluded from vector checks
    if "skip_vector_checks" in params:
        if params["skip_vector_checks"]:
            status.info("The delivery has been excluded from vector.overlap check because the vector data source does not contain a single object of interest.")
            return

    cursor = params["connection_manager"].get_connection().cursor()
    for layer_def in do_layers(params):
        log.debug("Started overlap check for the layer {:s}.".format(layer_def["pg_layer_name"]))

        # Check for number of polygons in vector layer
        cursor = params["connection_manager"].get_connection().cursor()
        sql_params = {"layer_name": layer_def["pg_layer_name"]}
        sql = "SELECT EXISTS (SELECT 1 FROM {layer_name});"
        sql = sql.format(**sql_params)
        cursor.execute(sql)
        any_polygon_in_vector = cursor.fetchone()[0]
        if not any_polygon_in_vector:
            status.info("There is no polygon to check in the vector layer.")
            return

        # Prepare support data.
        partitioned_layer = PartitionedLayer(cursor.connection, layer_def["pg_layer_name"], layer_def["pg_fid_name"])
        neighbour_table = NeighbourTable(partitioned_layer)
        neighbour_table.make()

        sql_params = {"fid_name": layer_def["pg_fid_name"],
                      "layer_name": layer_def["pg_layer_name"],
                      "neighbour_table": neighbour_table.neighbour_table_name,
                      "overlap_detail_table": "s{:02d}_{:s}_detail".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "overlap_suspect_table": "s{:02d}_{:s}_suspect".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "error_table": "s{:02d}_{:s}_error".format(params["step_nr"], layer_def["pg_layer_name"])}

        # FIXME:
        # It may happen during partitioning, that the splitted geometries may get shifted a bit.
        # The NeighbourTable then reports two neighbouring geometries as overlapping with ST_Dimension()=2.
        # In order to avoid reporting such misleading overlaps we verify the overlap by generating anew
        # intersection from original geometries.
        # If some overlaps are found actually, they are propagated into error table.
        # So, the order of building the tables are reversed, the content of error table is extracted
        # from the overlap detail table.

        # Create suspects table.
        sql = ("CREATE TABLE {overlap_suspect_table} AS\n"
               "(SELECT fida, fidb\n"
               "FROM {neighbour_table}\n"
               "WHERE\n"
               "fida < fidb\n"
               "AND dim >= 2);")
        sql = sql.format(**sql_params)
        log.debug(sql)
        cursor.execute(sql)
        if cursor.rowcount > 0:
            # Create overlap detail table.
            sql = ("CREATE TABLE {overlap_detail_table} AS\n"
                   "(SELECT fida, fidb, polygon_dump(ST_Intersection(layer_a.geom, layer_b.geom)) AS geom\n"
                   "FROM {overlap_suspect_table}\n"
                   "INNER JOIN {layer_name} AS layer_a ON {overlap_suspect_table}.fida = layer_a.{fid_name}\n"
                   "INNER JOIN {layer_name} AS layer_b ON {overlap_suspect_table}.fidb = layer_b.{fid_name});\n")

            sql = sql.format(**sql_params)
            log.debug("SQL QUERY:")
            log.debug(sql)
            cursor.execute(sql)
            if cursor.rowcount > 0:
                # Report overlap detail table.
                status.add_full_table(sql_params["overlap_detail_table"])

                # Create table of error items.
                sql = ("CREATE TABLE {error_table} AS\n"
                       "SELECT DISTINCT unnest(ARRAY[fida, fidb]) AS {fid_name}\n"
                       "FROM {overlap_detail_table};")
                sql = sql.format(**sql_params)
                cursor.execute(sql)

                # Report error items.
                items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
                status.failed("Layer {:s} has overlapping pairs in features with {:s}: {:s}."
                              .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
                status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

        log.info("Overlap check for the layer {:s} has been finished.".format(layer_def["pg_layer_name"]))
