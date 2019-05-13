#!/usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Vector and raster layer have similar area"
IS_SYSTEM = False


def run_check(params, status):
    import osgeo.gdal as gdal

    # Raster layer - total area of compared pixels
    raster_layer_alias = params["raster_layer"]

    raster_layer = params["raster_layer_defs"][raster_layer_alias]
    raster_ds = gdal.Open(str(raster_layer["src_filepath"]))
    histogram = raster_ds.GetRasterBand(1).GetHistogram(approx_ok=False)
    raster_area_pixel_count = 0
    for raster_area_code in params["raster_codes"]:
        raster_area_pixel_count += histogram[raster_area_code]

    raster_geotransform = raster_ds.GetGeoTransform()
    raster_cell_area = abs(raster_geotransform[1] * raster_geotransform[5])
    raster_area_sum = float(raster_area_pixel_count) * float(raster_cell_area)


    # Vector layer - total area of compared features
    vector_layer_alias = params["vector_layer"]
    vector_layer_def = params["layer_defs"][vector_layer_alias]

    cursor = params["connection_manager"].get_connection().cursor()

    # Prepare parameters used in sql clauses.
    sql_params = {"layer_name": vector_layer_def["pg_layer_name"],
                  "code_column_name": params["vector_code_column_name"]}

    # Create area sum query.
    sql = ("SELECT SUM(ST_Area(wkb_geometry)) FROM {layer_name}"
           " WHERE {code_column_name} = ANY(%s)")

    sql = sql.format(**sql_params)
    cursor.execute(sql, (params["vector_codes"],))

    # Get result area sum
    vector_area_sum = float(cursor.fetchone()[0])

    # Comparison of vector_area_sum and raster_area_sum
    area_difference = (raster_area_sum - vector_area_sum) / vector_area_sum

    # If difference is larger than than 0.1%, return an error.
    if abs(area_difference) > 0.001:
        status.failed("Area sums of raster and vector layer differ by more than 0.1% (actual difference is {:f} %)."
                      .format(area_difference * 100.0))
    # If difference is larger than 0.05% and smaller than 0.1%, return a warning.
    elif abs(area_difference) > 0.0005:
        status.info("Area sums of raster and vector layer differ by more than 0.05% (actual difference is {:f} %)."
                    .format(area_difference * 100.0))
