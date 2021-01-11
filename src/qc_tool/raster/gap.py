#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "There is no gap in the AOI."
IS_SYSTEM = False

MASK_ALIGN_GRID = 1000

def run_check(params, status):
    import subprocess
    import numpy
    import osgeo.gdal as gdal
    import osgeo.osr as osr

    from qc_tool.raster.helper import do_raster_layers
    from qc_tool.raster.helper import find_tiles
    from qc_tool.raster.helper import rasterize_mask
    from qc_tool.raster.helper import read_tile
    from qc_tool.raster.helper import write_progress
    from qc_tool.raster.helper import write_percent


    aoi_code = params["aoi_code"]
    gap_value_ds = params["outside_area_code"]
    du_column_name = params.get("du_column_name", None)
    mask_align_grid = params.get("mask_align_grid", MASK_ALIGN_GRID)

    # Find the external boundary raster mask layer.
    raster_boundary_dir = params["boundary_dir"].joinpath("raster")
    vector_boundary_dir = params["boundary_dir"].joinpath("vector")
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

        # Check availability of mask.

        # The mask is either retrieved from boundary package or it is generated using mask_ident, du_column_name and aoi_code.
        if mask_ident.endswith(".gpkg") or mask_ident.endswith(".shp"):
            mask_vector_filepath = vector_boundary_dir.joinpath(mask_ident)
            if not mask_vector_filepath.exists():
                status.info("Check cancelled due to boundary vector file {:s} not available.".format(mask_ident))
                return
            mask_file = rasterize_mask(mask_vector_filepath, int(ds_xres), params["du_column_name"], aoi_code,
                                       mask_align_grid, ds_ulx, ds_uly, params["output_dir"])
        else:
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
            if mask_ident.endswith(".gpkg") or mask_ident.endswith(".shp"):
                extent_message = "Layer {:s} does not intersect any AOI polygon with {:s}={:s} from boundary {:s}."
                extent_message = extent_message.format(layer_def["src_filepath"].name, du_column_name, aoi_code, mask_ident)
            else:
                extent_message = "Layer {:s} does not intersect the AOI mask {:s}."
                extent_message = extent_message.format(layer_def["src_layer_name"], mask_ident)
            extent_message += "Raster extent: [{:f} {:f}, {:f} {:f}]".format(ds_ulx, ds_uly, ds_lrx, ds_lry)
            extent_message += "AOI extent: [{:f} {:f}, {:f} {:f}]".format(mask_ulx, mask_uly, mask_lrx, mask_lry)
            status.info(extent_message)
            continue

        # Check if the raster and the AOI mask have the same resolution.
        if ds_xres != mask_xres or ds_yres != mask_yres:
            status.info("Resolution of the raster [{:f}, {:f}] does not match "
                        "the resolution [{:f}, {:f}] of the boundary mask {:s}.tif."
                        .format(ds_xres, ds_yres, mask_xres, mask_yres, mask_ident))
            continue

        # Check if coordinates of the raster origin are whole integers.
        if not ds_ulx.is_integer() or not ds_uly.is_integer():
            status.info("Coordinates of the raster origin ({:f}, {:f}) are not whole integers."
                        .format(ds_ulx, ds_uly))
            continue

        # Check if origin of mask is aligned with origin of raster.
        if abs(ds_ulx - mask_ulx) % ds_xres > 0:
            status.info("X coordinates of the raster are not exactly aligned with x coordinates of boundary mask."
                        "Raster origin: {:f}, Mask origin: {:f}".format(ds_ulx, mask_ulx))
            continue

        if abs(ds_uly - mask_uly) % ds_yres > 0:
            status.info("Y coordinates of the raster are not exactly aligned with Y coordinates of boundary mask."
                        "Raster origin: {:f}, Mask origin: {:f}".format(ds_uly, mask_uly))
            continue

        if report_progress:
            msg = "ds_ulx: {:f} mask_ulx: {:f}".format(ds_ulx, mask_ulx)
            msg += "\nds_uly: {:f} mask_uly: {:f}".format(ds_uly, mask_uly)
            msg += "\nRasterXSize: {:d} RasterYSize: {:d}".format(ds.RasterXSize, ds.RasterYSize)
            write_progress(progress_filepath, msg)

        # Find the tiles
        tiles = find_tiles(ds, mask_ds)
        if report_progress:
            write_progress(progress_filepath, "Number of tiles: {:d}".format(len(tiles)))

        # processing all the tiles:
        ds_band = ds.GetRasterBand(1)

        # retrieval of NoData value:
        if gap_value_ds == "NODATA":
            gap_value_ds = ds_band.GetNoDataValue()

        gap_count_total = 0
        num_tiles = len(tiles)
        gap_filepaths = []
        for tile_no, tile in enumerate(tiles):

            write_progress(progress_filepath, "Processing tile {}/{} ({}).".format(tile_no + 1, len(tiles), tile.position))

            # reading the mask data into Numpy array
            mask_xoff = tile.x_offset
            mask_yoff = tile.y_offset
            blocksize_x = tile.ncols
            blocksize_y = tile.nrows
            arr_mask = mask_band.ReadAsArray(mask_xoff, mask_yoff, blocksize_x, blocksize_y)

            # If mask has all values unmapped then mask / raster comparison can be skipped.
            if numpy.max(arr_mask) == 0 or numpy.min(arr_mask) == nodata_value_mask:
                write_progress(progress_filepath, "Tile {} has all values outside of mask, skipping.".format(tile_no + 1))
                continue

            if tile.position == "outside":
                # Current tile is completely outside the bounds of the checked raster.
                write_progress(progress_filepath, "tile_position: outside.")
                arr_gaps = (arr_mask == 1)
            elif tile.position == "inside":
                # Current tile is completely inside the bounds of the checked raster.
                arr_ds = read_tile(ds, tile, gap_value_ds)
                arr_gaps = ((arr_mask == 1) * (arr_ds == gap_value_ds))
            else:
                # Current tile is partially inside and partially outside the bounds of the checked raster.
                arr_ds = read_tile(ds, tile, gap_value_ds)
                arr_gaps = ((arr_mask == 1) * (arr_ds == gap_value_ds))

            # find unmapped pixels inside mask
            gap_count = int(numpy.sum(arr_gaps))
            if gap_count > 0:

                # For each mask tile with gaps, create a new warning raster dataset.
                # These datasets can be merged or polygonized at the end of the run.
                src_stem = layer_def["src_filepath"].stem
                gap_ds_filename = "s{:02d}_{:s}_gap_warning_{:d}.tif".format(params["step_nr"], src_stem, tile_no)
                gap_ds_filepath = params["tmp_dir"].joinpath(gap_ds_filename)
                driver = gdal.GetDriverByName('GTiff')
                gap_ds = driver.Create(str(gap_ds_filepath), blocksize_x, blocksize_y, 1, gdal.GDT_Byte, ['COMPRESS=LZW'])
                gap_ds.SetGeoTransform([tile.xmin, mask_xres, 0, tile.ymax, 0, mask_yres])
                gap_sr = osr.SpatialReference()
                gap_sr.ImportFromWkt(ds.GetProjectionRef())
                gap_ds.SetProjection(gap_sr.ExportToWkt())
                gap_band = gap_ds.GetRasterBand(1)
                gap_band.SetNoDataValue(0)
                gap_band.WriteArray(arr_gaps.astype("byte"), 0, 0)
                gap_ds.FlushCache()
                gap_ds = None
                gap_filepaths.append(str(gap_ds_filepath))
                gap_count_total += gap_count

            if report_progress:
                msg = "tile: {:d}/{:d} ({:s}), gaps: {:d}".format(tile_no + 1, num_tiles, tile.position, gap_count)
                write_progress(progress_filepath, msg)
                progress_percent = int(100 * (tile_no / num_tiles))
                write_percent(percent_filepath, progress_percent)


        # Free memory for checked raster and for mask.
        ds = None
        ds_mask = None

        # Generate attachments.
        if gap_count_total > 0:
            # Merge previously generated tile gap rasters into a .vrt
            src_stem = layer_def["src_filepath"].stem
            warning_vrt_filename = "s{:02d}_{:s}_gap_warning.vrt".format(params["step_nr"], src_stem)
            warning_vrt_filepath = params["tmp_dir"].joinpath(warning_vrt_filename)

            if len(gap_filepaths) > 0:
                cmd = ["gdalbuildvrt", str(warning_vrt_filepath)]
                cmd = cmd + gap_filepaths
                write_progress(progress_filepath, " ".join(cmd))
                subprocess.run(cmd)
                status.info("Layer {:s} has {:d} gap pixels in the mapped area."
                            .format(layer_def["src_layer_name"], gap_count_total))

            # Convert the .vrt to a GeoTiff
            if warning_vrt_filepath.is_file():
                warning_tif_filename = "s{:02d}_{:s}_gap_warning.tif".format(params["step_nr"], src_stem)
                warning_tif_filepath = params["output_dir"].joinpath(warning_tif_filename)
                cmd = ["gdal_translate",
                       "-of", "GTiff",
                       "-ot", "Byte",
                       "-co", "TILED=YES",
                       "-co", "COMPRESS=LZW",
                       str(warning_vrt_filepath),
                       str(warning_tif_filepath)]
                subprocess.run(cmd)
                status.add_attachment(warning_tif_filepath.name)
