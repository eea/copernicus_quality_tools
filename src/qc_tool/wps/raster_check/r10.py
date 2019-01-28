#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from pathlib import Path
import numpy
from osgeo import gdal
from osgeo import ogr
from osgeo import osr

from qc_tool.wps.registry import register_check_function
from qc_tool.wps.helper import zip_shapefile

def write_percent(percent_filepath, percent):
    percent_filepath.write_text(str(percent))

def write_progress(progress_filepath, message):
    with open(str(progress_filepath), "a") as f:
        f.write(message + "\n")

@register_check_function(__name__)
def run_check(params, status):

    # set this to true for writing partial progress to a text file.
    report_progress = True
    progress_filepath = params["output_dir"].joinpath(__name__.split(".")[-1] + "_progress.txt")
    percent_filepath = params["output_dir"].joinpath(__name__.split(".")[-1] + "_percent.txt")

    # Set the block size for reading raster in tiles. Reason: whole raster does not fit into memory.
    blocksize = 2048

    country_code = params["country_code"]

    # get raster resolution from the raster file
    ds = gdal.Open(str(params["filepath"]))

    # get raster corners and resolution
    ds_gt = ds.GetGeoTransform()
    ds_ulx = ds_gt[0]
    ds_xres = ds_gt[1]
    ds_uly = ds_gt[3]
    ds_yres = ds_gt[5]
    ds_lrx = ds_ulx + (ds.RasterXSize * ds_xres)
    ds_lry = ds_uly + (ds.RasterYSize * ds_yres)

    ds_band = ds.GetRasterBand(1)
    nodata_value_ds = params["outside_area_code"]


    # Find the external boundary raster mask layer.
    raster_boundary_dir = params["boundary_dir"].joinpath("raster")
    mask_ident = "default"
    if "mask" in params:
        mask_ident = params["mask"]

    mask_file = raster_boundary_dir.joinpath("mask_{:s}_{:03d}m_{:s}.tif".format(mask_ident, int(ds_xres), country_code))

    if not mask_file.exists():
        status.cancelled()
        status.add_message("Check cancelled due to boundary mask file {:s} not available.".format(mask_file.name),
                           failed=False)
        return
    mask_ds = gdal.Open(str(mask_file))
    if mask_ds is None:
        status.cancelled()
        status.add_message("Check cancelled due to boundary mask file {:s} not available.".format(mask_file.name),
                           failed=False)
        return
    mask_band = mask_ds.GetRasterBand(1)
    nodata_value_mask = mask_band.GetNoDataValue()

    # get aoi mask corners and resolution
    mask_gt = mask_ds.GetGeoTransform()
    mask_ulx = mask_gt[0]
    mask_xres = mask_gt[1]
    mask_uly = mask_gt[3]
    mask_yres = mask_gt[5]
    mask_lrx = ds_ulx + (mask_ds.RasterXSize * mask_xres)
    mask_lry = ds_uly + (mask_ds.RasterYSize * mask_yres)

    # Check if the dataset is fully covered by the mask.
    ds_inside_mask = (ds_ulx >= mask_ulx and ds_uly <= mask_uly and ds_lrx <= mask_lrx and ds_lry >= mask_lry)
    if not ds_inside_mask:
        extent_message = "raster is not fully contained inside the boundary mask {:s}.".format(mask_ident)
        extent_message += "raster extent: [{:f} {:f}, {:f} {:f}]".format(ds_ulx, ds_uly, ds_lrx, ds_lry)
        extent_message += "boundary mask extent: [{:f} {:f}, {:f} {:f}]".format(mask_ulx, mask_uly, mask_lrx, mask_lry)
        status.add_message(extent_message)
        return

    # Check if raster resolution and boundary mask resolution matches.
    if ds_xres != mask_xres or ds_yres != mask_yres:
        status.add_message("Resolution of the raster [{:f}, {:f}] does not match the "
                           "resolution [{:f}, {:f}] of the boundary mask {:s}.tif.".format(ds_xres, ds_yres, mask_xres,
                                                                                       mask_yres, mask_ident))
        return

    # Check if origin of mask is aligned with origin of raster
    if abs(ds_ulx - mask_ulx) % ds_xres > 0:
        status.add_message("X coordinates of the raster are not exactly aligned with x coordinates of boundary mask."
                           "Raster origin: {:f}, Mask origin: {:f}".format(ds_ulx, mask_ulx))
        return

    if abs(ds_uly - mask_uly) % ds_yres > 0:
        status.add_message("Y coordinates of the raster are not exactly aligned with Y coordinates of boundary mask."
                           "Raster origin: {:f}, Mask origin: {:f}".format(ds_uly, mask_uly))
        return

    # Calculate offset of checked raster dataset [ulx, uly] from boundary mask [ulx, uly].
    mask_add_cols = int(abs(ds_ulx - mask_ulx) / abs(ds_xres))
    mask_add_rows = int(abs(ds_uly - mask_uly) / abs(ds_yres))

    if report_progress:
        msg = "ds_ulx: {:f} mask_ulx: {:f} mask_add_cols: {:f}".format(ds_ulx, mask_ulx, mask_add_cols)
        msg += "\nds_uly: {:f} mask_uly: {:f} mask_add_rows: {:f}".format(ds_uly, mask_uly, mask_add_rows)
        msg += "\nRasterXSize: {:d} RasterYSize: {:d}".format(ds.RasterXSize, ds.RasterYSize)
        write_progress(progress_filepath, msg)

    n_block_cols = int(ds.RasterXSize / blocksize)
    n_block_rows = int(ds.RasterYSize / blocksize)

    # Handle special case when the last block in a row or column only partially covers the raster.
    last_block_width = blocksize
    last_block_height = blocksize

    if n_block_cols * blocksize < ds.RasterXSize:
        last_block_width = ds.RasterXSize - (n_block_cols * blocksize)
        n_block_cols = n_block_cols + 1

    if n_block_rows * blocksize < ds.RasterXSize:
        last_block_height = ds.RasterYSize - (n_block_rows * blocksize)
        n_block_rows = n_block_rows + 1

    if report_progress:
        write_progress(progress_filepath,
                       "n_block_rows: {:d} last_block_width: {:d}".format(n_block_rows, last_block_width))
        write_progress(progress_filepath,
                       "n_block_cols: {:d} last_block_height: {:d}".format(n_block_cols, last_block_height))

    # creating an OUTPUT dataset for writing error raster cells
    src_stem = params["filepath"].stem
    error_raster_filepath = params["output_dir"].joinpath(src_stem + "_completeness_error.tif")
    driver = gdal.GetDriverByName('GTiff')
    x_pixels = int(round(ds.RasterXSize))
    y_pixels = int(round(ds.RasterYSize))
    error_ds = driver.Create(str(error_raster_filepath), x_pixels, y_pixels, 1, gdal.GDT_Byte, ['COMPRESS=LZW'])
    error_ds.SetGeoTransform((ds_ulx, ds_xres, 0, ds_uly, 0, ds_yres))

    # set output projection
    error_sr = osr.SpatialReference()
    error_sr.ImportFromWkt(ds.GetProjectionRef())
    error_ds.SetProjection(error_sr.ExportToWkt())

    error_ds.GetRasterBand(1).SetNoDataValue(0)
    error_band = error_ds.GetRasterBand(1)

    # processing of mask is done in tiles (for better performance)
    nodata_count_total = 0
    ds_xoff = 0
    ds_yoff = 0
    for row in range(n_block_rows):

        if report_progress:
            write_progress(progress_filepath, "completeness check, row: {:d}/{:d}".format(row, n_block_rows))
            progress_percent = int(100 * ((row + 1) / n_block_rows))
            write_percent(percent_filepath, progress_percent)

        ds_xoff = 0
        blocksize_y = blocksize
        if row == n_block_rows - 1:
            blocksize_y = last_block_height # special case for last row
        for col in range(n_block_cols):
            blocksize_x = blocksize
            if col == n_block_cols - 1:
                blocksize_x = last_block_width # special case for last column

            # reading the block directly from the boundary mask dataset using computed offsets.
            arr_mask = mask_band.ReadAsArray(ds_xoff + mask_add_cols, ds_yoff + mask_add_rows, blocksize_x, blocksize_y)

            # if mask has all values unmapped => skip
            if numpy.max(arr_mask) == nodata_value_mask:
                continue

            # reading the block from the checked raster dataset.
            arr_ds = ds_band.ReadAsArray(ds_xoff, ds_yoff, blocksize_x, blocksize_y)

            arr_ds_unmapped = (arr_ds == nodata_value_ds)

            # if block in dataset has all cells mapped, then skip.
            if numpy.max(arr_ds_unmapped) == False:
                continue

            # find unmapped pixels inside mask
            arr_mask_bool = (arr_mask != nodata_value_mask)

            arr_nodata = (arr_ds_unmapped * arr_mask_bool)
            nodata_count = numpy.sum(arr_nodata)

            if nodata_count > 0:
                # write detected NoData pixels [subtracted < 0] to a the error raster.
                if report_progress:
                    msg = "row: {:d} col: {:d} num NoData pixels: {:d}".format(row, col, nodata_count)
                    write_progress(progress_filepath, msg)

                nodata_pixels = arr_nodata.astype('byte')
                error_band.WriteArray(nodata_pixels, ds_xoff, ds_yoff)

            nodata_count_total += nodata_count

            ds_xoff += blocksize
        ds_yoff += blocksize

    # free memory for checked raster and for boundary mask raster
    ds = None
    ds_mask = None

    if nodata_count_total == 0:
        # check is OK, no NoData pixels were detected inside mapped area.
        # clean up the empty error raster file.
        error_ds.FlushCache()
        error_ds = None
        error_raster_filepath.unlink()
        return

    else:
        # export the nodata_error raster to a shapefile using gdal_polygonize.
        error_shp_filepath = Path(str(error_raster_filepath).replace(".tif", ".shp"))
        error_layername = error_shp_filepath.stem
        drv = ogr.GetDriverByName("ESRI Shapefile")
        error_shp_ds = drv.CreateDataSource(str(error_shp_filepath))
        error_shp_srs = osr.SpatialReference()
        error_shp_srs.ImportFromWkt(error_ds.GetProjectionRef())
        dst_layer = error_shp_ds.CreateLayer(error_layername, srs=error_shp_srs)
        gdal.Polygonize(error_band, error_band, dst_layer, -1, [], callback=None)
        error_shp_ds.FlushCache()
        error_shp_ds = None

        error_filename = zip_shapefile(error_shp_filepath)
        status.add_attachment(error_filename)

        error_ds.FlushCache()
        error_ds = None

        status.add_message("{:d} NoData pixels were found in the mapped area.".format(nodata_count_total))
        return
