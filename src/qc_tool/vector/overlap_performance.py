#! /usr/bin/env python3


DESCRIPTION = "There is no couple of overlapping polygons."
IS_SYSTEM = False


def run_check(params, status):
    from qc_tool.vector.helper import do_layers
    from qc_tool.vector.helper import get_failed_items_message

    cursor = params["connection_manager"].get_connection().cursor()
    for layer_def in do_layers(params):
        # Prepare parameters used in sql clauses.
        sql_params = {"fid_name": layer_def["pg_fid_name"],
                      "layer_name": layer_def["pg_layer_name"],
                      "overlap_limit": "1",
                      "intersection_table": "s{:02d}_{:s}_intersection".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "subdivided_table": "s{:02d}_{:s}_subdivided".format(params["step_nr"], layer_def["pg_layer_name"]),
                      "error_table": "s{:02d}_{:s}_error".format(params["step_nr"], layer_def["pg_layer_name"])}

        # Create table of subdivided items.
        #sql = ("CREATE TABLE {subdivided_table_snapped} AS"
        #       "  (SELECT ST_SnapToGrid(ST_Subdivide(geom, 5000), 0.00001) AS geom,"
        #       "    {fid_name}"
        #       "   FROM {layer_name}"
        #       "  );"
        #       )
        #sql = sql.format(**sql_params)
        #cursor.execute(sql)


        #-- Subdivide
        #complex
        #geometries in table, in place


        # Create table of subdivided items.
        sql = ("CREATE TABLE {subdivided_table} AS"
               "  (SELECT (ST_Dump(ST_Subdivide(geom, 5000))).geom AS geom,"
               "    {fid_name} as orig_fid"
               "   FROM {layer_name}"
               "  );"
               )
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Create spatial index on the subdivided table.
        sql = ("CREATE INDEX {subdivided_table}_index"
               " ON {subdivided_table} USING GIST(geom);")
        sql = sql.format(**sql_params)
        cursor.execute(sql)
        status.add_full_table(sql_params["subdivided_table"])

        # Create table of intersections.
        #sql = ("CREATE TABLE {intersection_table} AS"
        #       "  SELECT DISTINCT unnest(ARRAY[ta.{fid_name}, tb.{fid_name}]) AS {fid_name}"
        #       "  FROM {subdivided_table} ta, {subdivided_table} tb"
        #       "  WHERE"
        #       "    ta.{fid_name} < tb.{fid_name}"
        #       "    AND ta.geom && tb.geom"
        #       "    AND ST_Relate(ST_MakeValid(ST_SNAP(ta.geom, tb.geom, 0.0001)), tb.geom, 'T********');")
        #sql = sql.format(**sql_params)
        #cursor.execute(sql)

        sql = ("CREATE TABLE {intersection_table} AS"
               "  SELECT ta.orig_fid as ta_fid, tb.orig_fid AS tb_fid, (ST_Dump(ST_Intersection(ta.geom, tb.geom))).geom AS geom"
               "  FROM {subdivided_table} ta, {subdivided_table} tb"
               "  WHERE"
               "    ta.orig_fid < tb.orig_fid"
               "    AND ta.geom && tb.geom"
               "    AND ST_Relate(ta.geom, tb.geom, 'T********');")
        sql = sql.format(**sql_params)
        cursor.execute(sql)
        status.failed("Some overlaps were found.")
        status.add_full_table(sql_params["intersection_table"])
        return


        # Create table of error items, using overlap with limit
        sql = ("CREATE TABLE {error_table} AS"
               " SELECT DISTINCT unnest(ARRAY[ta.{fid_name}, tb.{fid_name}]) AS {fid_name}"
               " FROM {subdivided_table} ta, {subdivided_table} tb"
               " WHERE"
               "  ta.{fid_name} < tb.{fid_name}"
               "  AND ta.geom && tb.geom"
               "  AND (NOT ST_Relate(ta.geom, tb.geom, '**T***T**')"
               "       OR NOT ST_IsEmpty(ST_Buffer(ST_Intersection(ta.geom, tb.geom), 100.0)));")
        sql = sql.format(**sql_params)
        cursor.execute(sql)

        # Report error items.
        items_message = get_failed_items_message(cursor, sql_params["error_table"], layer_def["pg_fid_name"])
        if items_message is not None:
            status.failed("Layer {:s} has overlapping pairs in features with {:s}: {:s}."
                          .format(layer_def["pg_layer_name"], layer_def["fid_display_name"], items_message))
            status.add_error_table(sql_params["error_table"], layer_def["pg_layer_name"], layer_def["pg_fid_name"])

            status.add_full_table(sql_params["intersection_table"])
