#!/bin/env python3
# -*- coding: utf-8 -*-


import re

from qc_tool.wps.helper import do_layers
from qc_tool.wps.helper import get_failed_items_message
from qc_tool.wps.registry import register_check_function


def count_table(cursor, table_name):
    sql = "SELECT count(*) FROM {:s};".format(table_name)
    cursor.execute(sql)
    count = cursor.fetchone()[0]
    return count

def create_table(cursor, pg_fid_name, new_table_name, orig_table_name):
    sql = "CREATE TABLE {0:s} AS SELECT {1:s} FROM {2:s} WHERE FALSE;"
    sql = sql.format(new_table_name, pg_fid_name, orig_table_name)
    cursor.execute(sql)

def drop_table(cursor, table_name):
    sql = "DROP TABLE IF EXISTS {:s};".format(table_name)
    cursor.execute(sql)

def subtract_table(cursor, pg_fid_name, first_table, second_table):
    sql = "DELETE FROM {0:s} USING {1:s} WHERE {0:s}.{2:s} = {1:s}.{2:s};"
    sql = sql.format(first_table, second_table, pg_fid_name)
    cursor.execute(sql)
    return cursor.rowcount

def create_all_breaking_mmu(cursor, pg_fid_name, pg_layer_name, error_table_name, area_m2):
    sql = ("CREATE TABLE {:s} AS"
           " SELECT {:s} FROM {:s}"
           " WHERE shape_area < %s;")
    sql = sql.format(error_table_name, pg_fid_name, pg_layer_name)
    cursor.execute(sql, [area_m2])
    return cursor.rowcount

def subtract_border_polygons(cursor, border_layer_name, pg_fid_name, pg_layer_name, error_table_name, except_table_name):
    """Subtracts polygons at boundary."""
    create_table(cursor, pg_fid_name, except_table_name, error_table_name)

    # Fill except table with polygons taken from error table and touching boundary.
    sql = ("WITH boundary AS ("
           "  SELECT ST_Boundary(ST_Union(wkb_geometry)) AS wkb_geometry FROM {0:s})"
           " INSERT INTO {1:s}"
           "  SELECT DISTINCT lt.{2:s}"
           "  FROM {3:s} lt INNER JOIN {4:s} et ON lt.{2:s} = et.{2:s}, boundary"
           "  WHERE ST_Intersects(lt.wkb_geometry, boundary.wkb_geometry);")
    sql = sql.format(border_layer_name,
                     except_table_name,
                     pg_fid_name,
                     pg_layer_name,
                     error_table_name)
    cursor.execute(sql)

    # Delete an item from error table if it is in except table already.
    subtract_table(cursor, pg_fid_name, error_table_name, except_table_name)

    error_count = count_table(cursor, error_table_name)
    except_count = count_table(cursor, except_table_name)
    return (error_count, except_count)

def subtract_inner_polygons(cursor, pg_fid_name, pg_layer_name, error_table_name, except_table_name, code_colname, area_m2):
    """Subtracts polygons smaller than MMU which are part of dissolved polygons greater than MMU."""
    sql = ("WITH"
           "  all_dissolved AS ("
           "    SELECT (ST_Dump(ST_Union(wkb_geometry))).geom geom FROM {0:s} GROUP BY {1:s}),"
           "  big_dissolved AS ("
           "    SELECT geom FROM all_dissolved WHERE ST_Area(geom) > %s)"
           " INSERT INTO {2:s}"
           "  SELECT lt.{3:s}"
           "  FROM {0:s} lt INNER JOIN {4:s} et ON lt.{3:s} = et.{3:s}, big_dissolved "
           "  WHERE ST_Within(lt.wkb_geometry, big_dissolved.geom);")
    sql = sql.format(pg_layer_name,
                     code_colname,
                     except_table_name,
                     pg_fid_name,
                     error_table_name,
                     pg_layer_name)
    cursor.execute(sql, [area_m2])

    # Delete an item from error table if it is in except table already.
    subtract_table(cursor, pg_fid_name, error_table_name, except_table_name)

    error_count = count_table(cursor, error_table_name)
    except_count = count_table(cursor, except_table_name)
    return (error_count, except_count)


@register_check_function(__name__)
def run_check(params, status):
    cursor = params["connection_manager"].get_connection().cursor()

    for layer_def in do_layers(params):
        if "code_regex" in params:
            mobj = re.search(params["code_regex"], layer_def["pg_layer_name"])
            code = mobj.group(1)
            code_colnames = params["code_to_column_names"][code]
            border_exception = True
        else:
            code_colnames = []
            border_exception = params["border_exception"]

        error_table_name = "{:s}_lessmmu_error".format(layer_def["pg_layer_name"])
        if not border_exception:
            # Status without border.
            error_count = create_all_breaking_mmu(cursor,
                                                  layer_def["pg_fid_name"],
                                                  layer_def["pg_layer_name"],
                                                  error_table_name,
                                                  params["area_m2"])
            except_count = 0
        else:
            except_table_name = "{:s}_lessmmu_except".format(layer_def["pg_layer_name"])
            create_all_breaking_mmu(cursor,
                                    layer_def["pg_fid_name"],
                                    layer_def["pg_layer_name"],
                                    error_table_name,
                                    params["area_m2"])
            (error_count, except_count) = subtract_border_polygons(cursor,
                                                                   params["layer_defs"]["boundary"]["pg_layer_name"],
                                                                   layer_def["pg_fid_name"],
                                                                   layer_def["pg_layer_name"],
                                                                   error_table_name,
                                                                   except_table_name)
            for code_colname in code_colnames:
                (error_count, except_count) = subtract_inner_polygons(cursor,
                                                                      layer_def["pg_fid_name"],
                                                                      layer_def["pg_layer_name"],
                                                                      error_table_name,
                                                                      except_table_name,
                                                                      code_colname,
                                                                      params["area_m2"])

        # Clean the tables.
        if error_count == 0:
            drop_table(cursor, error_table_name)
        else:
            failed_items_message = get_failed_items_message(cursor, error_table_name, layer_def["pg_fid_name"])
            failed_message = "The layer {:s} has polygons with area less then MMU in rows: {:s}.".format(layer_def["pg_layer_name"], failed_items_message)
            status.add_message(failed_message)
            status.add_error_table(error_table_name, layer_def["pg_layer_name"], layer_def["pg_fid_name"])
        if except_count == 0:
            drop_table(cursor, except_table_name)
        else:
            failed_items_message = get_failed_items_message(cursor, except_table_name, layer_def["pg_fid_name"])
            failed_message = "The layer {:s} has exceptional polygons with area less then MMU in rows: {:s}.".format(layer_nar_name, failed_items_message)
            status.add_message(failed_message, failed=False)
            status.add_error_table(except_table_name, layer_def["pg_layer_name"], layer_def["pg_fid_name"])
