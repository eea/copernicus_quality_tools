#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from pathlib import Path


DESCRIPTION = "There is no gap in the AOI."
IS_SYSTEM = False


def write_percent(percent_filepath, percent):
    percent_filepath.write_text(str(percent))

def write_progress(progress_filepath, message):
    with open(str(progress_filepath), "a") as f:
        f.write(message + "\n")

def run_check(params, status):
    import subprocess
    import numpy
    import osgeo.gdal as gdal
    import osgeo.ogr as ogr
    import osgeo.osr as osr

    from qc_tool.raster.helper import do_raster_layers

    # Set the block size for reading raster in tiles. Reason: whole raster does not fit into memory.
    blocksize = 2048
    aoi_code = params["aoi_code"]
    nodata_value_ds = params["outside_area_code"]

    # Find the external boundary raster mask layer.
    raster_boundary_dir = params["boundary_dir"].joinpath("raster")
    mask_ident = "default"
    if "mask" in params:
        mask_ident = params["mask"]

    for layer_def in do_raster_layers(params):

        # set this to true for writing partial progress to a text file.
        report_progress = True
        progress_filename = "{:s}_{:s}_progress.txt".format(__name__.split(".")[-1], layer_def["src_filepath"].stem)
        progress_filepath = params["output_dir"].joinpath(progress_filename)
        percent_filename = "{:s}_{:s}_percent.txt".format(__name__.split(".")[-1], layer_def["src_filepath"].stem)
        percent_filepath = params["output_dir"].joinpath(percent_filename)

        # get raster corners and resolution
        ds = gdal.Open(str(layer_def["src_filepath"]))
        ds_gt = ds.GetGeoTransform()
        ds_ulx = ds_gt[0]
        ds_xres = ds_gt[1]
        ds_uly = ds_gt[3]
        ds_yres = ds_gt[5]
        ds_lrx = ds_ulx + (ds.RasterXSize * ds_xres)
        ds_lry = ds_uly + (ds.RasterYSize * ds_yres)

        mask_file = raster_boundary_dir.joinpath("mask_{:s}_{:03d}m_{:s}.tif".format(mask_ident, int(ds_xres), aoi_code))

        if not mask_file.exists():
            status.info("Check cancelled due to boundary mask file {:s} not available.".format(mask_file.name))
            return
        mask_ds = gdal.Open(str(mask_file))
        if mask_ds is None:
            status.info("Check cancelled due to boundary mask file {:s} not available.".format(mask_file.name))
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

        # Check if the dataset extent intersects the mask extent.
        if (mask_ulx > ds_lrx or mask_uly < ds_lry or mask_lrx < ds_ulx or mask_lry > ds_uly):
            extent_message = "Layer {:s} does not intersect the aoi mask {:s}."
            extent_message = extent_message.format(layer_def["src_layer_name"], mask_ident)
            extent_message += "raster extent: [{:f} {:f}, {:f} {:f}]".format(ds_ulx, ds_uly, ds_lrx, ds_lry)
            extent_message += "aoi mask extent: [{:f} {:f}, {:f} {:f}]".format(mask_ulx, mask_uly, mask_lrx, mask_lry)
            status.info(extent_message)
            continue

        # Check if the dataset is fully covered by the mask.
        ds_inside_mask = (ds_ulx >= mask_ulx and ds_uly <= mask_uly and ds_lrx <= mask_lrx and ds_lry >= mask_lry)
        if not ds_inside_mask:
            # If the dataset is not fully covered by the mask, then expand the mask extent to the raster extent
            # (extended mask pixels inside raster extent but outside original mask extent are set to NoData)
            mask_ds = None
            mask_file_extended = params["tmp_dir"].joinpath(mask_file.name.replace(".tif", "_extended.tif"))
            raster_epsg = "EPSG:3035"
            cmd = ["gdalwarp",
                   "-dstnodata", str(nodata_value_mask),
                   "-t_srs", raster_epsg,
                   "-s_srs", raster_epsg,
                   "-te_srs", raster_epsg,
                   "-tr", str(ds_xres), str(ds_xres),
                   "-r", "near",
                   "-te", str(ds_ulx), str(ds_lry), str(ds_lrx), str(ds_uly),
                   "-ot", "Byte",
                   "-of", "GTiff",
                   "-co", "TILED=YES",
                   "-co", "COMPRESS=LZW",
                   str(mask_file),
                   str(mask_file_extended)]

            subprocess.check_output(cmd)
            mask_ds = gdal.Open(str(mask_file_extended))
            mask_band = mask_ds.GetRasterBand(1)
            mask_gt = mask_ds.GetGeoTransform()
            mask_ulx = mask_gt[0]
            mask_xres = mask_gt[1]
            mask_uly = mask_gt[3]
            mask_yres = mask_gt[5]

        # Check if raster resolution and boundary mask resolution matches.
        if ds_xres != mask_xres or ds_yres != mask_yres:
            status.info("Resolution of the raster [{:f}, {:f}] does not match "
                          "the resolution [{:f}, {:f}] of the boundary mask {:s}.tif."
                          .format(ds_xres, ds_yres, mask_xres, mask_yres, mask_ident))
            continue

        # Check if origin of mask is aligned with origin of raster
        if abs(ds_ulx - mask_ulx) % ds_xres > 0:
            status.info("X coordinates of the raster are not exactly aligned with x coordinates of boundary mask."
                          "Raster origin: {:f}, Mask origin: {:f}".format(ds_ulx, mask_ulx))
            continue

        if abs(ds_uly - mask_uly) % ds_yres > 0:
            status.info("Y coordinates of the raster are not exactly aligned with Y coordinates of boundary mask."
                          "Raster origin: {:f}, Mask origin: {:f}".format(ds_uly, mask_uly))
            continue

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

        # creating an OUTPUT dataset for writing warning raster cells
        src_stem = layer_def["src_filepath"].stem
        warning_raster_filename = "s{:02d}_{:s}_gap_warning.tif".format(params["step_nr"], src_stem)
        warning_raster_filepath = params["output_dir"].joinpath(warning_raster_filename)
        driver = gdal.GetDriverByName('GTiff')
        x_pixels = int(round(ds.RasterXSize))
        y_pixels = int(round(ds.RasterYSize))
        warning_raster_ds = driver.Create(str(warning_raster_filepath), x_pixels, y_pixels, 1, gdal.GDT_Byte, ['COMPRESS=LZW'])
        warning_raster_ds.SetGeoTransform((ds_ulx, ds_xres, 0, ds_uly, 0, ds_yres))

        # set output projection
        warning_sr = osr.SpatialReference()
        warning_sr.ImportFromWkt(ds.GetProjectionRef())
        warning_raster_ds.SetProjection(warning_sr.ExportToWkt())

        warning_band = warning_raster_ds.GetRasterBand(1)
        warning_band.SetNoDataValue(0)

        # processing of mask is done in tiles (for better performance)
        nodata_count_total = 0
        ds_xoff = 0
        ds_yoff = 0
        ds_band = ds.GetRasterBand(1)
        for row in range(n_block_rows):

            if report_progress:
                write_progress(progress_filepath, "completeness check, row: {:d}/{:d}".format(row, n_block_rows))
                progress_percent = int(90 * ((row + 1) / n_block_rows))
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
                if numpy.max(arr_mask) == 0:
                    continue

                # reading the block from the checked raster dataset.
                arr_ds = ds_band.ReadAsArray(ds_xoff, ds_yoff, blocksize_x, blocksize_y)

                arr_ds_mapped = (arr_ds != nodata_value_ds).astype(int)
                arr_mask_mapped = (arr_mask != nodata_value_mask).astype(int)
                arr_nodata = ((arr_ds_mapped - arr_mask_mapped) < 0)

                # find unmapped pixels inside mask
                nodata_count = int(numpy.sum(arr_nodata))

                if nodata_count > 0:
                    # write detected NoData pixels [subtracted < 0] to a the warning raster.
                    if report_progress:
                        msg = "row: {:d} col: {:d} num NoData pixels: {:d}".format(row, col, nodata_count)
                        write_progress(progress_filepath, msg)

                    nodata_pixels = arr_nodata.astype('byte')
                    warning_band.WriteArray(nodata_pixels, ds_xoff, ds_yoff)

                nodata_count_total += nodata_count

                ds_xoff += blocksize
            ds_yoff += blocksize

        # free memory for checked raster and for boundary mask raster
        ds = None
        ds_mask = None

        if nodata_count_total == 0:
            # check is OK, no gap pixels were detected inside mapped area.
            # clean up the empty warning raster file.
            warning_raster_ds.FlushCache()
            warning_raster_ds = None
            warning_raster_filepath.unlink()
            continue

        else:
            # Vectorize the warning raster and export it to geopackage.
            warning_dsrc_filepath = Path(str(warning_raster_filepath).replace(".tif", ".gpkg"))
            warning_layername = warning_dsrc_filepath.stem
            drv = ogr.GetDriverByName("GPKG")
            warning_dsrc = drv.CreateDataSource(str(warning_dsrc_filepath))
            warning_srs = osr.SpatialReference()
            warning_srs.ImportFromWkt(warning_raster_ds.GetProjectionRef())
            warning_layer = warning_dsrc.CreateLayer(warning_layername, srs=warning_srs)
            gdal.Polygonize(warning_band, warning_band, warning_layer, -1, [], callback=None)
            warning_dsrc.FlushCache()
            warning_dsrc = None
            status.add_attachment(warning_dsrc_filepath.name)
            status.info("Layer {:s} has {:d} gap pixels in the mapped area."
                        .format(layer_def["src_layer_name"], nodata_count_total))

            # Flush warning raster.
            warning_raster_ds.FlushCache()
            warning_raster_ds = None
            status.add_attachment(warning_raster_filepath.name)
