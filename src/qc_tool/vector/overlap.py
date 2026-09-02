#! /usr/bin/env python3

import logging

DESCRIPTION = "There is no couple of overlapping polygons."
IS_SYSTEM = False

DEFAULT_OVERLAP_AREA_TOLERANCE = 1e-6  # square metres
DEFAULT_OVERLAP_WIDTH_TOLERANCE = 1e-6  # metres

log = logging.getLogger(__name__)


def run_check(params, status):
    from qc_tool.vector.helper import PartitionedLayer, NeighbourTable, do_layers, get_failed_items_message

    # Check if the current delivery is excluded from vector checks
    if params.get("skip_vector_checks"):
        status.info(
            "The delivery has been excluded from vector.overlap check because the vector data source does not contain a single object of interest."
        )
        return

    overlap_area_tolerance = params.get("overlap_area_tolerance", DEFAULT_OVERLAP_AREA_TOLERANCE)
    overlap_width_tolerance = params.get("overlap_width_tolerance", DEFAULT_OVERLAP_WIDTH_TOLERANCE)
    overlap_negative_buffer = overlap_width_tolerance * -0.5

    cursor = params["connection_manager"].get_connection().cursor()

    for layer_def in do_layers(params):
        log.debug("Started overlap check for the layer %s.", layer_def["pg_layer_name"])

        # Check for number of polygons in vector layer
        sql_params = {"layer_name": layer_def["pg_layer_name"]}
        sql = "SELECT EXISTS (SELECT 1 FROM {layer_name});".format(**sql_params)
        cursor.execute(sql)
        if not cursor.fetchone()[0]:
            status.info("There is no polygon to check in the vector layer.")
            continue

        # Prepare support data
        partitioned_layer = PartitionedLayer(cursor.connection, layer_def["pg_layer_name"], layer_def["pg_fid_name"])
        neighbour_table = NeighbourTable(partitioned_layer)
        neighbour_table.make()

        sql_params = {
            "fid_name": layer_def["pg_fid_name"],
            "layer_name": layer_def["pg_layer_name"],
            "neighbour_table": neighbour_table.neighbour_table_name,
            "overlap_detail_table": f"s{params['step_nr']:02d}_{layer_def['pg_layer_name']}_detail",
            "overlap_suspect_table": f"s{params['step_nr']:02d}_{layer_def['pg_layer_name']}_suspect",
            "error_table": f"s{params['step_nr']:02d}_{layer_def['pg_layer_name']}_error",
            "overlap_exception_table": f"s{params['step_nr']:02d}_{layer_def['pg_layer_name']}_exception",
            "overlap_area_tolerance": str(overlap_area_tolerance),
            "overlap_width_tolerance": str(overlap_width_tolerance),
            "overlap_negative_buffer": str(overlap_negative_buffer),
        }

        # Create suspects table
        sql_suspects = """
            CREATE TABLE {overlap_suspect_table} AS
            SELECT fida, fidb
            FROM {neighbour_table}
            WHERE fida < fidb AND dim >= 2;
        """.format(**sql_params)
        cursor.execute(sql_suspects)

        cursor.execute("SELECT count(*) FROM {overlap_suspect_table};".format(**sql_params))
        num_suspects = cursor.fetchone()[0]

        if num_suspects > 0:
            # Build WHERE clauses dynamically based on enabled tolerances
            if overlap_area_tolerance > 0 and overlap_width_tolerance > 0:
                # Exception if AREA <= tolerance OR WIDTH <= tolerance
                where_exception = """
                    ST_Dimension(geom) = 2 
                    AND (
                        ST_Area(geom) <= {overlap_area_tolerance} 
                        OR ST_Area(ST_Buffer(geom, {overlap_negative_buffer})) = 0
                    )
                """.format(**sql_params)

                # Error ONLY if AREA > tolerance AND WIDTH > tolerance
                where_error = """
                    ST_Dimension(geom) = 2 
                    AND ST_Area(geom) > {overlap_area_tolerance} 
                    AND ST_Area(ST_Buffer(geom, {overlap_negative_buffer})) > 0
                """.format(**sql_params)

                exception_msg = "Layer {:s} has {:d} overlap exceptions with area <= {:s} or width <= {:s} tolerance."

            elif overlap_area_tolerance > 0:
                where_exception = "ST_Dimension(geom) = 2 AND ST_Area(geom) <= {overlap_area_tolerance}".format(**sql_params)
                where_error = "ST_Dimension(geom) = 2 AND ST_Area(geom) > {overlap_area_tolerance}".format(**sql_params)
                exception_msg = "Layer {:s} has {:d} overlap exceptions with area <= {:s} tolerance."

            else:
                where_exception = None
                where_error = "ST_Dimension(geom) = 2"
                exception_msg = ""

            # 1. Process Exceptions
            if where_exception:
                sql_exceptions = f"""
                    CREATE TABLE {{overlap_exception_table}} AS
                    WITH inters AS (
                        SELECT fida, fidb, (ST_Dump(ST_Intersection(layer_a.geom, layer_b.geom))).geom AS geom
                        FROM {{overlap_suspect_table}}
                        INNER JOIN {{layer_name}} AS layer_a ON {{overlap_suspect_table}}.fida = layer_a.{{fid_name}}
                        INNER JOIN {{layer_name}} AS layer_b ON {{overlap_suspect_table}}.fidb = layer_b.{{fid_name}}
                    )
                    SELECT * FROM inters WHERE {where_exception};
                """.format(**sql_params)
                
                cursor.execute(sql_exceptions)
                cursor.execute("SELECT count(*) FROM {overlap_exception_table};".format(**sql_params))
                num_exceptions = cursor.fetchone()[0]

                if num_exceptions > 0:
                    status.add_full_table(sql_params["overlap_exception_table"])
                    if overlap_width_tolerance > 0:
                        status.info(exception_msg.format(layer_def["pg_layer_name"], num_exceptions, str(overlap_area_tolerance), str(overlap_width_tolerance)))
                    else:
                        status.info(exception_msg.format(layer_def["pg_layer_name"], num_exceptions, str(overlap_area_tolerance)))

            # 2. Process Errors
            sql_error_detail = f"""
                CREATE TABLE {{overlap_detail_table}} AS
                WITH inters AS (
                    SELECT fida, fidb, (ST_Dump(ST_Intersection(layer_a.geom, layer_b.geom))).geom AS geom
                    FROM {{overlap_suspect_table}}
                    INNER JOIN {{layer_name}} AS layer_a ON {{overlap_suspect_table}}.fida = layer_a.{{fid_name}}
                    INNER JOIN {{layer_name}} AS layer_b ON {{overlap_suspect_table}}.fidb = layer_b.{{fid_name}}
                )
                SELECT * FROM inters WHERE {where_error};
            """.format(**sql_params)
            
            cursor.execute(sql_error_detail)
            cursor.execute("SELECT count(*) FROM {overlap_detail_table};".format(**sql_params))
            num_errors = cursor.fetchone()[0]

            if num_errors > 0:
                status.add_full_table(sql_params["overlap_detail_table"])
                sql_error_items = (
                    "CREATE TABLE {error_table} AS\n"
                    "SELECT DISTINCT unnest(ARRAY[fida, fidb]) AS {fid_name}\n"
                    "FROM {overlap_detail_table};"
                )
                cursor.execute(sql_error_items.format(**sql_params))
                items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
                status.failed(
                    "Layer {:s} has overlapping pairs in features with {:s}: {:s}.".format(
                        layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message
                    )
                )
                status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

        log.info("Overlap check for the layer {:s} has been finished.".format(layer_def["pg_layer_name"]))