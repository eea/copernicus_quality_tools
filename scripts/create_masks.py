#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Script creating raster masks of european countries.
"""


from datetime import datetime
from math import ceil
from math import floor
from pathlib import Path

import osgeo.ogr as ogr
import osgeo.gdal as gdal


def enlarge_to_grid(xmin, ymin, xmax, ymax, pixel_size):
    xmin = floor(xmin / pixel_size) * pixel_size
    ymin = floor(ymin / pixel_size) * pixel_size
    xmax = ceil(xmax / pixel_size) * pixel_size
    ymax = ceil(ymax / pixel_size) * pixel_size
    return (xmin, ymin, xmax, ymax)

def get_size(xmin, ymin, xmax, ymax, pixel_size):
    return (int((xmax - xmin) / pixel_size), int((ymax - ymin) / pixel_size))

def main(pixel_size=5):
    gdal.UseExceptions()
    ogr.UseExceptions()

    dest_path = Path("/mnt/pracovni-archiv-01/projects/cop15m/swf_masks/deflate")
    src_path = Path("/home/ikratochvil/userdoc/gisat/cop15m/swf_masks")

    # Open datasource of boundary polygons.
    src_filepath = src_path.joinpath("VHR_Image_2015_CCMs_CC/euroboundarymap_diss_grid_3035_14012014_CCMs_CC.shp")
    src_dsrc = ogr.Open(str(src_filepath))
    src_layer = src_dsrc.GetLayerByIndex(0)

    for i in range(src_layer.GetFeatureCount()):

        # Get feature and its fid.
        print(datetime.now())
        src_feature = src_layer.GetFeature(i)
        print("orig fid:", src_feature.GetFID())
        eurofid = src_feature["FID_eurobo"]
        print("eurofid:", eurofid)

        # Enlarge bounding box to grid.
        (xmin, xmax, ymin, ymax) = src_feature.geometry().GetEnvelope()
        print("orig bbox:", (xmin, ymin, xmax, ymax))
        (xmin, ymin, xmax, ymax) = enlarge_to_grid(xmin, ymin, xmax, ymax, pixel_size)
        print("grid bbox:", (xmin, ymin, xmax, ymax))
        width, height = get_size(xmin, ymin, xmax, ymax, pixel_size)
        print("size:", (width, height))

        # Create a new layer containing current feature only.
        mem_dsrc = ogr.GetDriverByName("memory").CopyDataSource(src_dsrc, "memory")
        mem_layer = mem_dsrc.GetLayerByIndex(0)
        for mem_feature in mem_layer:
            if mem_feature["FID_eurobo"] != eurofid:
                mem_layer.DeleteFeature(mem_feature.GetFID())

        # Prepare raster dataset.
        mem_drv = gdal.GetDriverByName("MEM")
        mem_ds = mem_drv.Create("memory", width, height, 1, gdal.GDT_Byte)
        mem_ds.SetProjection(src_layer.GetSpatialRef().ExportToWkt())
        mem_ds.SetGeoTransform((xmin, pixel_size, 0, ymax, 0, -pixel_size))
        mem_ds.GetRasterBand(1).SetNoDataValue(0)
        mem_ds.GetRasterBand(1).Fill(0)
        gdal.RasterizeLayer(mem_ds, [1], mem_layer, burn_values=(1,))

        # Store raster dataset.
        dest_filename = "mask_swf_005_{:03d}.tif".format(eurofid)
        dest_filepath = dest_path.joinpath(dest_filename)
        dest_driver = gdal.GetDriverByName("GTiff")
        dest_ds = dest_driver.CreateCopy(str(dest_filepath), mem_ds, False, options=["COMPRESS=DEFLATE", "ZLEVEL=9"])

        # Remove temporary datasource and datasets from memory.
        mem_dsrc = None
        mem_ds = None
        dest_ds = None
        
        print(datetime.now())

if __name__ == "__main__":
    main()
