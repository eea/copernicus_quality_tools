#!/usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Vector and raster layer have similar area"
IS_SYSTEM = False


def run_check(params, status):
    import osgeo.gdal as gdal

    # Check if the current delivery is excluded from vector checks
    if "skip_vector_checks" in params:
        if params["skip_vector_checks"]:
            status.info("The delivery has been excluded from vector.layer_area check because the vector data source does not contain a single object of interest.")
            return

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
    sql = ("SELECT SUM(ST_Area(geom)) FROM {layer_name}"
           " WHERE {code_column_name} = ANY(%s)")

    sql = sql.format(**sql_params)
    cursor.execute(sql, (params["vector_codes"],))

    # Get result area sum
    vector_area_sum = cursor.fetchone()[0]

    if vector_area_sum is None and raster_area_sum == 0:
        status.info("There is no valid vector feature and area sum of raster layer is 0.")
        return

    vector_area_sum = float(vector_area_sum)

    # Comparison of vector_area_sum and raster_area_sum
    area_difference = ((raster_area_sum - vector_area_sum) / vector_area_sum) * 100.0

    # If difference is larger than than error_percent_difference, return an error.
    if abs(area_difference) > params["error_percent_difference"]:
        status.failed("Area sums of raster and vector layer differ by more than {:.2f}% (actual difference is {:f}%)."
                      .format(params["error_percent_difference"], area_difference))
    # If difference is larger than error_percent_difference
    # and smaller than warning_percent_differnce, return a warning.
    elif abs(area_difference) > params["warning_percent_difference"]:
        status.info("Area sums of raster and vector layer differ by more than {:.2f}% (actual difference is {:f}%)."
                    .format(params["warning_percent_difference"], area_difference))
