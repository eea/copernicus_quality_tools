#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Script creating raster boundary layers based on set of the reference boundary layers and source pan-european boundary mosaic
"""

import os
import re
import subprocess

import osgeo.ogr as ogr
import osgeo.gdal as gdal

REFERENCE_FILES_DIR = "/home/jtomicek/copernicus_quality_tools/qc_tool_boundary/boundaries/raster/"
BOUNDARY_MOSAIC = "/home/jtomicek/Documents/qctool_eea39_boundary_update/eea_r_3035_20_m_copernicus-buffer_p_2012-2018_v03_r00/Boundary_EEA39_03035_020m.tif"
RESULTS_DIR = "/home/jtomicek/Documents/qctool_eea39_boundary_update/results"
REFERENCE_FILES_REGEX = "^mask_eea38uk_010m_"


def dir_recursive_search(in_dir, regexp=".*", target="file", deep=9999, full_path=True):
    results = []
    level = 0
    for root, dirs, files in os.walk(in_dir):
        res = [f for f in os.listdir(root) if re.search(r'%s' % regexp, f)]
        for f in res:
            path = os.path.join(root, f)
            if ((target == "file" and os.path.isfile(path)) or (target == "dir" and os.path.isdir(path))) and (
                    level <= deep):
                if full_path:
                    results.append(path)
                else:
                    results.append(f)
        level += 1
    return results


def get_raster_extent(raster_path):
    dataset = gdal.Open(raster_path)
    if not dataset:
        raise ValueError("Could not open the raster file.")

    # Get geotransform
    gt = dataset.GetGeoTransform()

    # Get raster size
    x_size = dataset.RasterXSize
    y_size = dataset.RasterYSize

    # Calculate extent
    xmin = gt[0]
    xmax = xmin + (x_size * gt[1])  # top-left x + width in pixel units
    ymax = gt[3]
    ymin = ymax + (y_size * gt[5])  # top-left y + height in pixel units

    return {"xmin": str(xmin), "ymin": str(ymin), "xmax": str(xmax), "ymax": str(ymax)}

def get_pixel_size(raster_path):
    dataset = gdal.Open(raster_path)
    if not dataset:
        raise ValueError("Could not open the raster file.")

    # Get geotransform
    return dataset.GetGeoTransform()[1]


def main(reference_files_dir, boundary_mosaic, results_dir, reference_files_regex):
    gdal.UseExceptions()
    ogr.UseExceptions()

    # get boundary mosaic pixel size
    target_pixel_size = get_pixel_size(boundary_mosaic)
    if len(str(int(target_pixel_size))) == 2:
        target_pixel_size_str = f"0{int(target_pixel_size)}m"
    else:
        target_pixel_size_str = f"{int(target_pixel_size)}m"

    print(target_pixel_size, target_pixel_size_str)

    # get list of reference boundary layers
    ref_boundary_layers = dir_recursive_search(reference_files_dir, regexp=reference_files_regex)

    tile_codes_generated = list()

    for ref_boundary_layer in ref_boundary_layers:

        boundary_tile_extent = get_raster_extent(ref_boundary_layer)

        boundary_tile_code = os.path.basename(ref_boundary_layer).split("_")[-1].rstrip(".tif")
        if str(boundary_tile_code).lower() != "eu":
            continue

        result_file_path = os.path.join(results_dir, f"mask_eea38uk_{target_pixel_size_str}_{boundary_tile_code}.tif")
        if os.path.isfile(result_file_path):
            os.remove(result_file_path)

        warp_cmd = ["gdalwarp",
                    "-tr", str(target_pixel_size), str(target_pixel_size),
                    "-te", boundary_tile_extent["xmin"], boundary_tile_extent["ymin"], boundary_tile_extent["xmax"], boundary_tile_extent["ymax"],
                    "-co", "COMPRESS=DEFLATE",
                    boundary_mosaic, result_file_path]

        subprocess.check_output(warp_cmd)

        if get_pixel_size(result_file_path) != target_pixel_size:
            print(f"{result_file_path} has wrong pixel size!")
        else:
            tile_codes_generated.append(f"{boundary_tile_code}")

    print(tile_codes_generated)



if __name__ == "__main__":
    reference_files_dir = REFERENCE_FILES_DIR
    boundary_mosaic = BOUNDARY_MOSAIC
    results_dir = RESULTS_DIR
    reference_files_regex=REFERENCE_FILES_REGEX
    main(reference_files_dir=reference_files_dir,
         boundary_mosaic=boundary_mosaic,
         results_dir=results_dir,
         reference_files_regex=REFERENCE_FILES_REGEX)
