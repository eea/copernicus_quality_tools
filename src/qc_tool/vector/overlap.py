#! /usr/bin/env python3


import logging


DESCRIPTION = "There is no couple of overlapping polygons."
IS_SYSTEM = False

DEFAULT_OVERLAP_AREA_TOLERANCE = 1e-6 # square metres
DEFAULT_OVERLAP_WIDTH_TOLERANCE = 1e-6 # metres

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

    # overlap_area_tolerance optional parameter - to allow higher tolerance for overlaps
    # e.g to ignore very small overlaps due to floating-point precision errors (area in m2)
    overlap_area_tolerance = params.get("overlap_area_tolerance", DEFAULT_OVERLAP_AREA_TOLERANCE)

    overlap_width_tolerance = params.get("overlap_width_tolerance", DEFAULT_OVERLAP_WIDTH_TOLERANCE)

    overlap_negative_buffer = overlap_width_tolerance  * -0.5 # negative buffer: half of overlap width tolerance.

    cursor = params["connection_manager"].get_connection().cursor()
    for layer_def in do_layers(params):
        log.debug("Started overlap check for the layer {:s}.".format(layer_def["pg_layer_name"]))

        # Check for number of polygons in vector layer
        sql_params = {"layer_name": layer_def["pg_layer_name"]}
        sql = "SELECT EXISTS (SELECT 1 FROM {layer_name});".format(**sql_params)
        cursor.execute(sql)
        any_polygon_in_vector = cursor.fetchone()[0]
        if not any_polygon_in_vector:
            status.info("There is no polygon to check in the vector layer.")
            continue

        # Prepare support data.
        partitioned_layer = PartitionedLayer(cursor.connection, layer_def["pg_layer_name"], layer_def["pg_fid_name"])
        neighbour_table = NeighbourTable(partitioned_layer)
        neighbour_table.make()

        sql_params = {"fid_name": layer_def["pg_fid_name"],
                      "layer_name": layer_def["pg_layer_name"],
                      "neighbour_table": neighbour_table.neighbour_table_name,
                      "overlap_detail_table": "s{:02d}_{:s}_detail".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "overlap_suspect_table": "s{:02d}_{:s}_suspect".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "error_table": "s{:02d}_{:s}_error".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "overlap_exception_table": "s{:02d}_{:s}_exception".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "overlap_area_tolerance": str(overlap_area_tolerance),
                      "overlap_width_tolerance": str(overlap_width_tolerance),
                      "overlap_negative_buffer": str(overlap_negative_buffer)}

        # FIXME:
        # It may happen during partitioning, that the splitted geometries may get shifted a bit.
        # The NeighbourTable then reports two neighbouring geometries as overlapping with ST_Dimension()=2.
        # In order to avoid reporting such misleading overlaps we verify the overlap by generating anew
        # intersection from original geometries.
        # If some overlaps are found actually, they are propagated into error table.
        # So, the order of building the tables are reversed, the content of error table is extracted
        # from the overlap detail table.

        # Create suspects table.
        sql_suspects = ("CREATE TABLE {overlap_suspect_table} AS\n"
                        "(SELECT fida, fidb\n"
                        "FROM {neighbour_table}\n"
                        "WHERE\n"
                        "fida < fidb\n"
                        "AND dim >= 2);")
        sql_suspects = sql_suspects.format(**sql_params)
        log.debug(sql_suspects)
        cursor.execute(sql_suspects)

        cursor.execute("SELECT count(*) FROM {overlap_suspect_table};".format(**sql_params))
        num_suspects = cursor.fetchone()[0]

        if num_suspects > 0:
            if overlap_area_tolerance > 0 and overlap_width_tolerance > 0:
                # Both area and width tolerances are set.
                sql_exceptions = ("""
                CREATE TABLE {overlap_exception_table} AS
                WITH inters AS (
                SELECT fida,
                        fidb,
                        (ST_Dump(ST_Intersection(layer_a.geom, layer_b.geom))).geom AS geom
                FROM {overlap_suspect_table}
                INNER JOIN {layer_name} AS layer_a
                    ON {overlap_suspect_table}.fida = layer_a.{fid_name}
                INNER JOIN {layer_name} AS layer_b
                    ON {overlap_suspect_table}.fidb = layer_b.{fid_name}
                )
                SELECT *
                FROM inters
                WHERE ST_Dimension(geom) = 2 AND (ST_Area(geom) <= {overlap_area_tolerance} OR ST_Area(ST_buffer(geom, {overlap_negative_buffer})) = 0)
                """)
                cursor.execute(sql_exceptions.format(**sql_params))
                cursor.execute("SELECT count(*) FROM {overlap_exception_table};".format(**sql_params))
                num_exceptions = cursor.fetchone()[0]
                if num_exceptions > 0:
                    status.add_full_table(sql_params["overlap_exception_table"])
                    status.info("Layer {:s} has {:d} overlap exceptions with area < {:s} or width < {:s} tolerance."
                                .format(layer_def["pg_layer_name"], num_exceptions, str(overlap_area_tolerance), str(overlap_width_tolerance)))

                sql_error_detail = ("""
                CREATE TABLE {overlap_detail_table} AS
                WITH inters AS (
                SELECT fida,
                        fidb,
                        (ST_Dump(ST_Intersection(layer_a.geom, layer_b.geom))).geom AS geom
                FROM {overlap_suspect_table}
                INNER JOIN {layer_name} AS layer_a
                    ON {overlap_suspect_table}.fida = layer_a.{fid_name}
                INNER JOIN {layer_name} AS layer_b
                    ON {overlap_suspect_table}.fidb = layer_b.{fid_name}
                )
                SELECT *
                FROM inters
                WHERE ST_Area(geom) > {overlap_area_tolerance} OR ST_Area(ST_buffer(geom, {overlap_negative_buffer})) > 0
                """)
                cursor.execute(sql_error_detail.format(**sql_params))
                cursor.execute("SELECT count(*) FROM {overlap_detail_table};".format(**sql_params))
                num_errors = cursor.fetchone()[0]
                if num_errors > 0:
                    status.add_full_table(sql_params["overlap_detail_table"])
                    sql_error_items = ("CREATE TABLE {error_table} AS\n"
                                       "SELECT DISTINCT unnest(ARRAY[fida, fidb]) AS {fid_name}\n"
                                       "FROM {overlap_detail_table};")
                    cursor.execute(sql_error_items.format(**sql_params))
                    items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
                    status.failed("Layer {:s} has overlapping pairs in features with {:s}: {:s}."
                                  .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
                    status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

            elif overlap_area_tolerance > 0:
                # Only area tolerance is set, width tolerance is not used.
                sql_exceptions = ("""
                CREATE TABLE {overlap_exception_table} AS
                WITH inters AS (
                SELECT fida,
                        fidb,
                        (ST_Dump(ST_Intersection(layer_a.geom, layer_b.geom))).geom AS geom
                FROM {overlap_suspect_table}
                INNER JOIN {layer_name} AS layer_a
                    ON {overlap_suspect_table}.fida = layer_a.{fid_name}
                INNER JOIN {layer_name} AS layer_b
                    ON {overlap_suspect_table}.fidb = layer_b.{fid_name}
                )
                SELECT *
                FROM inters
                WHERE ST_Dimension(geom) = 2 AND ST_Area(geom) <= {overlap_area_tolerance}
                """)
                cursor.execute(sql_exceptions.format(**sql_params))
                cursor.execute("SELECT count(*) FROM {overlap_exception_table};".format(**sql_params))
                num_exceptions = cursor.fetchone()[0]
                if num_exceptions > 0:
                    status.add_full_table(sql_params["overlap_exception_table"])
                    status.info("Layer {:s} has {:d} overlap exceptions with area < {:s} tolerance."
                                .format(layer_def["pg_layer_name"], num_exceptions, str(overlap_area_tolerance)))

                sql_error_detail = ("""
                CREATE TABLE {overlap_detail_table} AS
                WITH inters AS (
                SELECT fida,
                        fidb,
                        (ST_Dump(ST_Intersection(layer_a.geom, layer_b.geom))).geom AS geom
                FROM {overlap_suspect_table}
                INNER JOIN {layer_name} AS layer_a
                    ON {overlap_suspect_table}.fida = layer_a.{fid_name}
                INNER JOIN {layer_name} AS layer_b
                    ON {overlap_suspect_table}.fidb = layer_b.{fid_name}
                )
                SELECT *
                FROM inters
                WHERE ST_Area(geom) > {overlap_area_tolerance}
                """)
                cursor.execute(sql_error_detail.format(**sql_params))
                cursor.execute("SELECT count(*) FROM {overlap_detail_table};".format(**sql_params))
                num_errors = cursor.fetchone()[0]
                if num_errors > 0:
                    status.add_full_table(sql_params["overlap_detail_table"])
                    sql_error_items = ("CREATE TABLE {error_table} AS\n"
                                       "SELECT DISTINCT unnest(ARRAY[fida, fidb]) AS {fid_name}\n"
                                       "FROM {overlap_detail_table};")
                    cursor.execute(sql_error_items.format(**sql_params))
                    items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
                    status.failed("Layer {:s} has overlapping pairs in features with {:s}: {:s}."
                                  .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
                    status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

            else:
                # No tolerance filtering: all 2D intersections are errors.
                sql_error_detail = ("""
                CREATE TABLE {overlap_detail_table} AS
                WITH inters AS (
                SELECT fida,
                        fidb,
                        (ST_Dump(ST_Intersection(layer_a.geom, layer_b.geom))).geom AS geom
                FROM {overlap_suspect_table}
                INNER JOIN {layer_name} AS layer_a
                    ON {overlap_suspect_table}.fida = layer_a.{fid_name}
                INNER JOIN {layer_name} AS layer_b
                    ON {overlap_suspect_table}.fidb = layer_b.{fid_name}
                )
                SELECT *
                FROM inters
                WHERE ST_Dimension(geom) = 2
                """)
                cursor.execute(sql_error_detail.format(**sql_params))
                cursor.execute("SELECT count(*) FROM {overlap_detail_table};".format(**sql_params))
                num_errors = cursor.fetchone()[0]
                if num_errors > 0:
                    status.add_full_table(sql_params["overlap_detail_table"])
                    sql_error_items = ("CREATE TABLE {error_table} AS\n"
                                       "SELECT DISTINCT unnest(ARRAY[fida, fidb]) AS {fid_name}\n"
                                       "FROM {overlap_detail_table};")
                    cursor.execute(sql_error_items.format(**sql_params))
                    items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
                    status.failed("Layer {:s} has overlapping pairs in features with {:s}: {:s}."
                                  .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
                    status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

        log.info("Overlap check for the layer {:s} has been finished.".format(layer_def["pg_layer_name"]))
