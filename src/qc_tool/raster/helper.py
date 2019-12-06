#!/usr/bin/env python3


from collections import namedtuple
import numpy

BLOCKSIZE = 2048


Tile = namedtuple("Tile", ["xmin", "ymin", "xmax", "ymax", "position", "x_offset", "y_offset", "ncols", "nrows"])


def do_raster_layers(params):
    if "layers" in params:
        return [params["raster_layer_defs"][layer_alias] for layer_alias in params["layers"]]
    else:
        return params["raster_layer_defs"].values()


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


def find_tiles(src_ds, mask_ds):
    tiles = []

    # parameters of the ds..
    ds_gt = src_ds.GetGeoTransform()
    ds_xmin = int(ds_gt[0])
    ds_xres = int(ds_gt[1])
    ds_ymax = int(ds_gt[3])
    ds_yres = int(ds_gt[5])
    ds_xmax = int(ds_xmin + (src_ds.RasterXSize * ds_xres))
    ds_ymin = int(ds_ymax + (src_ds.RasterYSize * ds_yres))

    mask_band = mask_ds.GetRasterBand(1)

    # get aoi mask corners and resolution
    mask_gt = mask_ds.GetGeoTransform()
    mask_ulx = int(mask_gt[0])
    mask_xres = int(mask_gt[1])
    mask_uly = int(mask_gt[3])
    mask_yres = int(mask_gt[5])

    n_block_cols = int(mask_ds.RasterXSize / BLOCKSIZE)
    n_block_rows = int(mask_ds.RasterYSize / BLOCKSIZE)

    # Handle special case when the last block in a row or column only partially covers the raster.
    last_block_width = BLOCKSIZE
    last_block_height = BLOCKSIZE

    if n_block_cols * BLOCKSIZE < mask_ds.RasterXSize:
        last_block_width = mask_ds.RasterXSize - (n_block_cols * BLOCKSIZE)
        n_block_cols = n_block_cols + 1

    if n_block_rows * BLOCKSIZE < mask_ds.RasterYSize:
        last_block_height = mask_ds.RasterYSize - (n_block_rows * BLOCKSIZE)
        n_block_rows = n_block_rows + 1

    mask_yoff = 0
    for row in range(n_block_rows):
        mask_xoff = 0
        blocksize_y = BLOCKSIZE
        if row == n_block_rows - 1:
            blocksize_y = last_block_height  # special case for last row

        # tile upper and lower bounds in absolute coordinates.
        tile_ymax = mask_uly + (mask_yoff * mask_yres)
        tile_ymin = mask_uly + (mask_yoff + blocksize_y) * mask_yres

        for col in range(n_block_cols):
            blocksize_x = BLOCKSIZE
            if col == n_block_cols - 1:
                blocksize_x = last_block_width  # special case for last column

            # tile left and right bounds in absolute coordinates.
            tile_xmin = mask_ulx + (mask_xoff * mask_xres)
            tile_xmax = mask_ulx + (mask_xoff + blocksize_x) * mask_xres

            if tile_xmax < ds_xmin or tile_xmin > ds_xmax or tile_ymin > ds_ymax or tile_ymax < ds_ymin:
                tiles.append(Tile(tile_xmin, tile_ymin, tile_xmax, tile_ymax, "outside", mask_xoff, mask_yoff, blocksize_x, blocksize_y))
            elif tile_xmin >= ds_xmin and tile_xmax <= ds_xmax and tile_ymin >= ds_ymin and tile_ymax <= ds_ymax:
                tiles.append(Tile(tile_xmin, tile_ymin, tile_xmax, tile_ymax, "inside", mask_xoff, mask_yoff, blocksize_x, blocksize_y))
            else:
                tiles.append(Tile(tile_xmin, tile_ymin, tile_xmax, tile_ymax, "overlap", mask_xoff, mask_yoff, blocksize_x, blocksize_y))
            mask_xoff += blocksize_x
        mask_yoff += blocksize_y
    return tiles


def read_tile(src_ds, tile, gap_value):
    """
    Reads raster data from a partially overlapping tile into a 2D array.
    :param src_ds: The source GDAL raster dataset.
    :param tile: Named tuple (Tile) with coordinates and size of the tile
    :param nodata_value:
    :return: A 2D array with the data. Pixels out of src_ds bounds have their values set to gap_value.
    """

    # Extract bounds of the dataset in absolute coordinates.
    ds_gt = src_ds.GetGeoTransform()
    ds_xmin = ds_gt[0]
    ds_xres = ds_gt[1]
    ds_ymax = ds_gt[3]
    ds_yres = ds_gt[5]
    ds_xmax = ds_xmin + (src_ds.RasterXSize * ds_xres)
    ds_ymin = ds_ymax + (src_ds.RasterYSize * ds_yres)

    ds_rect = Rectangle(ds_xmin, ds_ymin, ds_xmax, ds_ymax)
    tile_rect = Rectangle(tile.xmin, tile.ymin, tile.xmax, tile.ymax)

    # Find out if the tile bounds intersect with the dataset bounds.
    if tile_rect.intersection(ds_rect):
        intersection_rect = tile_rect.intersection(ds_rect)

        if intersection_rect is not None:
            arr_whole = (numpy.ones((tile.nrows, tile.ncols)) * gap_value).astype(int)

            intersection_xoff = int((intersection_rect.x1 - ds_xmin) / ds_xres)
            intersection_yoff = int((intersection_rect.y2 - ds_ymax) / ds_yres)
            intersection_width = int((intersection_rect.x2 - intersection_rect.x1) / ds_xres)
            intersection_height = int((intersection_rect.y2 - intersection_rect.y1) / abs(ds_yres))
            arr_intersection = src_ds.GetRasterBand(1).ReadAsArray(intersection_xoff, intersection_yoff,
                                                                   intersection_width, intersection_height)

            # Fill the subset of arr_whole with the values of arr_intersection.
            whole_xoff = int((intersection_rect.x1 - tile.xmin) / ds_xres)
            whole_yoff = int((intersection_rect.y2 - tile.ymax) / ds_yres)
            arr_whole[whole_yoff:whole_yoff+intersection_height, whole_xoff:whole_xoff+intersection_width] = arr_intersection
            return arr_whole
    else:
        arr_whole = (numpy.ones((tile.nrows, tile.ncols)) * gap_value).astype(int)
        return arr_whole
