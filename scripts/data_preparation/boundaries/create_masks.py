#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create per-feature European country masks from a projected boundary layer.

Manual utility requiring the historical FID_eurobo attribute and explicit source
and output paths. Existing outputs are replaced. Pixel size defaults to 5 metres;
the historical mask_swf_005 filename prefix is retained for every pixel size.
This script is not an automated QC check or a boundary publication command.
"""
import argparse
from datetime import datetime
from math import ceil
from math import floor
from pathlib import Path



def enlarge_to_grid(xmin, ymin, xmax, ymax, pixel_size):
    xmin = floor(xmin / pixel_size) * pixel_size
    ymin = floor(ymin / pixel_size) * pixel_size
    xmax = ceil(xmax / pixel_size) * pixel_size
    ymax = ceil(ymax / pixel_size) * pixel_size
    return (xmin, ymin, xmax, ymax)

def get_size(xmin, ymin, xmax, ymax, pixel_size):
    return (int((xmax - xmin) / pixel_size), int((ymax - ymin) / pixel_size))

def main(source_file, output_dir, pixel_size=5):
    import osgeo.ogr as ogr
    import osgeo.gdal as gdal
    gdal.UseExceptions()
    ogr.UseExceptions()

    dest_path = Path(output_dir)

    # Open datasource of boundary polygons.
    src_filepath = Path(source_file)
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True,
                        help="Projected source boundary file with FID_eurobo attributes")
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="Existing output directory; matching outputs are replaced")
    parser.add_argument("--pixel-size", type=float, default=5,
                        help="Grid pixel size (default: %(default)s; filenames retain the historical 005 prefix)")
    args = parser.parse_args()
    main(source_file=args.source, output_dir=args.output_dir, pixel_size=args.pixel_size)
