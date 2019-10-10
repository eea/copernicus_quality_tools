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


class Rectangle:
    def __init__(self, x1, y1, x2, y2):
        if x1 > x2 or y1 > y2:
            raise ValueError("Coordinates are invalid")
        self.x1, self.y1, self.x2, self.y2 = x1, y1, x2, y2

    def intersection(self, other):
        a, b = self, other
        x1 = max(min(a.x1, a.x2), min(b.x1, b.x2))
        y1 = max(min(a.y1, a.y2), min(b.y1, b.y2))
        x2 = min(max(a.x1, a.x2), max(b.x1, b.x2))
        y2 = min(max(a.y1, a.y2), max(b.y1, b.y2))
        if x1<x2 and y1<y2:
            return type(self)(x1, y1, x2, y2)

    def contains(self, r2):
        return self.x1 < r2.x1 < r2.x2 < self.x2 and self.y1 < r2.y1 < r2.y2 < self.y2

    def __iter__(self):
        yield self.x1
        yield self.y1
        yield self.x2
        yield self.y2

    def __eq__(self, other):
        return isinstance(other, Rectangle) and tuple(self) == tuple(other)

    def __ne__(self, other):
        return not (self == other)

    def __repr__(self):
        return type(self).__name__ + repr(tuple(self))


def read_tile(src_ds, tile_xmin, tile_xmax, tile_ymin, tile_ymax, tile_ncols, tile_nrows, nodata_value):

    import numpy

    """
    Reads a GDAL raster band into a numpy array.
    Pixels out of bounds are filled with noData value
    """
    print("source raster: {:d} columns, {:d} rows.".format(src_ds.RasterXSize, src_ds.RasterYSize))


    # parameters of the ds..
    ds_gt = src_ds.GetGeoTransform()
    ds_ulx = ds_gt[0]
    ds_xres = ds_gt[1]
    ds_uly = ds_gt[3]
    ds_yres = ds_gt[5]
    ds_lrx = ds_ulx + (src_ds.RasterXSize * ds_xres)
    ds_lry = ds_uly + (src_ds.RasterYSize * ds_yres)

    ds_xmax = ds_lrx
    ds_ymax = ds_uly
    ds_xmin = ds_ulx
    ds_ymin = ds_lry


    # CASE 2, dataset completely outside the mask

    print("ds_xmin: {:f}".format(ds_xmin))
    print("ds_xmax: {:f}".format(ds_xmax))
    print("ds_ymin: {:f}".format(ds_ymin))
    print("ds_ymax: {:f}".format(ds_ymax))

    print("tile_xmin: {:f}".format(tile_xmin))
    print("tile_xmax: {:f}".format(tile_xmax))
    print("tile_ymin: {:f}".format(tile_ymin))
    print("tile_ymax: {:f}".format(tile_ymax))

    ds_rect = Rectangle(ds_xmin, ds_ymin, ds_xmax, ds_ymax)
    tile_rect = Rectangle(tile_xmin, tile_ymin, tile_xmax, tile_ymax)

    # CASE 1, dataset does not overlap with the tile.
    #if tile_rect.x1 <= ds_rect.x1 and tile_rect.x2 >= ds_rect.x2 and tile_rect.y1 <= ds_rect.y1 and tile_rect.y2 <= ds_rect.y2:
    if tile_rect.contains(ds_rect):
        print("DATASET completely inside the tile !!!")

    elif ds_rect.contains(tile_rect):
        print("TILE completely inside the dataset !!!")

    elif tile_rect.intersection(ds_rect):
        print("TILE partially intersects with the dataset!")
        intersection_rect = tile_rect.intersection(ds_rect)
        print("tile_rect_intersection:")
        print(intersection_rect)

        if intersection_rect is not None:
            print("partial intersection!")
            arr_whole = (numpy.ones((tile_nrows, tile_ncols)) * nodata_value).astype(int)

            intersection_xoff = int((intersection_rect.x1 - ds_xmin) / ds_xres)
            intersection_yoff = int((intersection_rect.y2 - ds_ymax) / ds_yres)
            intersection_width = int((intersection_rect.x2 - intersection_rect.x1) / ds_xres)
            intersection_height = int((intersection_rect.y2 - intersection_rect.y1) / abs(ds_yres))

            print("intersection_xoff: {:d}".format(intersection_xoff))
            print("intersection_yoff: {:d}".format(intersection_yoff))
            print("intersection_width: {:d}".format(intersection_width))
            print("intersection_height: {:d}".format(intersection_height))
            arr_intersection = src_ds.GetRasterBand(1).ReadAsArray(intersection_xoff, intersection_yoff, intersection_width, intersection_height)
            print("arr_intersection:")
            print(arr_intersection)

            # insert arr_whole into arr_intersection:
            whole_xoff = int((intersection_rect.x1 - tile_xmin) / ds_xres)
            whole_yoff = int((intersection_rect.y2 - tile_ymax) / ds_yres)
            print("whole_xoff: {:d}".format(whole_xoff))
            print("whole_yoff: {:d}".format(whole_yoff))
            arr_whole[whole_yoff:whole_yoff+intersection_height, whole_xoff:whole_xoff+intersection_width] = arr_intersection
            print("arr_whole after filling:")
            print(arr_whole)
            return arr_whole
    else:
        print("NO INTERSECTION of tile and dataset!")
        arr_whole = (numpy.ones((tile_nrows, tile_ncols)) * nodata_value).astype(int)
        return arr_whole


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
        ds_nrows = ds.RasterYSize
        ds_ncols = ds.RasterXSize

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
        #ds_inside_mask = (ds_ulx >= mask_ulx and ds_uly <= mask_uly and ds_lrx <= mask_lrx and ds_lry >= mask_lry)

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
        ds_add_cols = int(abs(mask_ulx - ds_ulx) / abs(ds_xres))
        ds_add_rows = int(abs(mask_uly - ds_uly) / abs(ds_yres))

        print("ds_add_cols: {:d}".format(ds_add_cols))
        print("ds_add_rows: {:d}".format(ds_add_rows))

        if report_progress:
            msg = "ds_ulx: {:f} mask_ulx: {:f} ds_add_cols: {:f}".format(ds_ulx, mask_ulx, ds_add_cols)
            msg += "\nds_uly: {:f} mask_uly: {:f} ds_add_rows: {:f}".format(ds_uly, mask_uly, ds_add_rows)
            msg += "\nRasterXSize: {:d} RasterYSize: {:d}".format(ds.RasterXSize, ds.RasterYSize)
            write_progress(progress_filepath, msg)

        n_block_cols = int(mask_ds.RasterXSize / blocksize)
        n_block_rows = int(mask_ds.RasterYSize / blocksize)

        # Handle special case when the last block in a row or column only partially covers the raster.
        last_block_width = blocksize
        last_block_height = blocksize

        if n_block_cols * blocksize < mask_ds.RasterXSize:
            last_block_width = mask_ds.RasterXSize - (n_block_cols * blocksize)
            n_block_cols = n_block_cols + 1

        if n_block_rows * blocksize < ds.RasterXSize:
            last_block_height = mask_ds.RasterYSize - (n_block_rows * blocksize)
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
        mask_x_pixels = int(round(mask_ds.RasterXSize))
        mask_y_pixels = int(round(mask_ds.RasterYSize))
        warning_raster_ds = driver.Create(str(warning_raster_filepath), mask_x_pixels, mask_y_pixels, 1,
                                          gdal.GDT_Byte, ['COMPRESS=LZW'])
        warning_raster_ds.SetGeoTransform((mask_ulx, mask_xres, 0, mask_uly, 0, mask_yres))

        # set output projection
        warning_sr = osr.SpatialReference()
        warning_sr.ImportFromWkt(ds.GetProjectionRef())
        warning_raster_ds.SetProjection(warning_sr.ExportToWkt())

        warning_band = warning_raster_ds.GetRasterBand(1)
        warning_band.SetNoDataValue(0)

        # processing of mask is done in tiles (for better performance)
        nodata_count_total = 0
        mask_yoff = 0
        ds_band = ds.GetRasterBand(1)
        for row in range(n_block_rows):

            if report_progress:
                write_progress(progress_filepath, "completeness check, row: {:d}/{:d}".format(row, n_block_rows))
                progress_percent = int(90 * ((row + 1) / n_block_rows))
                write_percent(percent_filepath, progress_percent)

            mask_xoff = 0
            blocksize_y = blocksize
            if row == n_block_rows - 1:
                blocksize_y = last_block_height # special case for last row
            for col in range(n_block_cols):
                blocksize_x = blocksize
                if col == n_block_cols - 1:
                    blocksize_x = last_block_width # special case for last column

                # reading the mask data into Numpy array
                arr_mask = mask_band.ReadAsArray(mask_xoff, mask_yoff, blocksize_x, blocksize_y)
                print("mask array:")
                print(arr_mask)

                # if mask has all values unmapped => skip
                if numpy.max(arr_mask) == 0:
                    continue

                # reading the block from the checked raster dataset using computed offsets.
                tile_xmin = mask_ulx + mask_xoff * mask_xres * blocksize_x
                tile_xmax = tile_xmin + mask_xres * blocksize_x

                tile_ymax = mask_uly + mask_yoff * mask_yres * blocksize_y
                tile_ymin = tile_ymax + mask_yres * blocksize_y

                # reading equivalent raster data into numpy array
                arr_ds = read_tile(ds,
                                   tile_xmin,
                                   tile_xmax,
                                   tile_ymin,
                                   tile_ymax,
                                   blocksize_x,
                                   blocksize_y,
                                   nodata_value_ds)

                arr_ds_mapped = (arr_ds != nodata_value_ds).astype(int)
                arr_mask_mapped = (arr_mask == 1).astype(int)
                arr_nodata = ((arr_ds_mapped - arr_mask_mapped) < 0)

                print("gaps in the mapped area:")
                print(arr_nodata.astype(int))

                # find unmapped pixels inside mask
                nodata_count = int(numpy.sum(arr_nodata))

                if nodata_count > 0:
                    # write detected NoData pixels [subtracted < 0] to a the warning raster.
                    if report_progress:
                        msg = "row: {:d} col: {:d} num NoData pixels: {:d}".format(row, col, nodata_count)
                        write_progress(progress_filepath, msg)
                        print(msg)
                        print(mask_xoff)
                        print(mask_yoff)

                    nodata_pixels = arr_nodata.astype('byte')
                    warning_band.WriteArray(nodata_pixels, mask_xoff, mask_yoff)

                nodata_count_total += nodata_count

                mask_xoff += blocksize
            mask_yoff += blocksize

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
