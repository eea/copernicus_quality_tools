import math
import numpy
from osgeo import gdal
from osgeo import ogr
from osgeo import osr
from skimage import measure

from qc_tool.wps.helper import zip_shapefile
from qc_tool.wps.registry import register_check_function


def convert_area_to_pixels(raster_ds, area_m2):
    """
    Convert MMU in square metres to MMU in pixels.
    :param raster_ds: GDAL raster dataset
    :param area_m2: value in square meters
    :return:
    """
    gt = raster_ds.GetGeoTransform()
    x_res = gt[1]
    y_res = gt[5]
    one_pixel_m2 = abs(x_res * y_res)
    area_pixels = math.ceil(area_m2 / one_pixel_m2)
    return area_pixels


def reclassify_values(arr, groups):
    """
    Assign the same value to all pixels belonging to a group.
    For example if group is [1, 2, 3] then all pixels with values of 1 or 2 or 3 will have value=1 assigned.
    Values not belonging to any group are not changed.
    :param arr: 2D numpy array
    :param groups: list of lists, for example [[1, 2], [253, 254, 255]]
    :return: a new reclassified array.
    """
    arr_copy = numpy.copy(arr)
    for group in groups:
        new_value = group[0]
        for value in group:
            if value != new_value:
                arr_copy[arr == value] = new_value
    return arr_copy


def patch_touches_cell_with_value(coordinates, tile, neighbour_values):
    """
    Takes a list of [row, column] cell coordinates and inspects if at least one of the coordinates
    has a neighbour cell having value in [values].
    This function can be used for detecting patches touching cloud or patches touching ocean.
    :param coordinates: The patch of same-value raster cells.
    :param tile: The numpy array raster tile to take values from.
    :param neighbour_values: A 1d array of integer values to comapare the neighbour cells with.
    :return: True if at least one neighbouring cell has one of neighbour_values, false othervise
    """
    for coor in coordinates:
        c_down = coor[0] + 1
        c_up = coor[0] - 1
        c_right = coor[1] + 1
        c_left = coor[1] - 1

        # top neighbour
        if c_up >= 0:
            if tile[c_up, coor[1]] in neighbour_values:
                return True
        # bottom neighbour
        if c_down < tile.shape[0]:
            if tile[c_down, coor[1]] in neighbour_values:
                return True
        # left neighbour
        if c_left >= 0:
            if tile[coor[0], c_left] in neighbour_values:
                return True
        # right neighbour
        if c_right < tile.shape[1]:
            if tile[coor[0], c_right] in neighbour_values:
                return True
    return False


def export_shapefile(regions, raster_ds, shp_filepath):
    """
    Exports a list of lessMMU region dictionaries to a point shapefile
    :param regions: list of dicts with {"coords", "area", "value"}
    :param raster_ds: original raster dataset
    :param shp_filepath: exported shapefile
    """
    if len(regions) > 0:

        (upper_left_x, x_size, x_rotation, upper_left_y, y_rotation, y_size) = raster_ds.GetGeoTransform()

        srs = osr.SpatialReference()
        srs.ImportFromWkt(raster_ds.GetProjection())

        driver = ogr.GetDriverByName('ESRI Shapefile')
        shapeData = driver.CreateDataSource(str(shp_filepath))

        layer = shapeData.CreateLayer('ogr_pts', srs, ogr.wkbPoint)
        areaField = ogr.FieldDefn("area_px", ogr.OFTInteger)
        layer.CreateField(areaField)
        valueField = ogr.FieldDefn("value", ogr.OFTInteger)
        layer.CreateField(valueField)

        layerDefinition = layer.GetLayerDefn()

        i = 0
        for rInfo in regions:
            x_proj = rInfo["coords"][0][0] * x_size + upper_left_x + (x_size / 2)  # add half the cell size
            y_proj = rInfo["coords"][0][1] * y_size + upper_left_y + (y_size / 2)  # to centre the point
            area = rInfo["area"]

            point = ogr.Geometry(ogr.wkbPoint)
            point.SetPoint(0, x_proj, y_proj)

            feature = ogr.Feature(layerDefinition)
            feature.SetGeometry(point)
            feature.SetFID(i)
            feature.SetField("area_px", int(area))
            feature.SetField("value", int(rInfo["value"]))

            layer.CreateFeature(feature)

            i += 1
        shapeData.Destroy()


@register_check_function(__name__)
def run_check(params, status):

    # set this to true for printing partial progress to standard output.
    report_progress = False

    # The checked raster is not read into memory as a whole. Instead it is read in tiles.
    # Instead, ReadAsArray is used to read subsets of the raster (tiles) on demand.
    ds = gdal.Open(str(params["filepath"]))

    # Determine if a "reclassify" step is required based on the "groupcodes" parameter setting.
    if "groupcodes" in params and params["groupcodes"] is not None and len(params["groupcodes"]) > 0:
        use_reclassify = True
    else:
        use_reclassify = False

    # NoData value can optionally be set as parameter
    # cell values with NODATA are excluded from MMU analysis.
    if "nodata_value" in params:
        NODATA = params["nodata_value"]
    else:
        NODATA = ds.GetRasterBand(1).GetNoDataValue()

    # size of a raster tile. Should be a multiple of 256 because GeoTiff stores its data in 256*256 pixel blocks.
    BLOCKSIZE = 2048
    MMU = params["area_pixels"]

    # Some classes can optionally be excluded from MMU requirements.
    # Pixels belonging to these classes are reported as exceptions.
    if "exclude_values" in params:
        exclude_values = params["exclude_values"]
    else:
        exclude_values = []

    # neighbouring values to exclude.
    # patches with area < MMU which touch a patch having class in neighbour_exclude_values are reported
    # as exceptions.
    if "neighbour_exclude_values" in params:
        neighbour_exclude_values = params["neighbour_exclude_values"]
    else:
        neighbour_exclude_values = []

    nRasterCols = ds.RasterXSize
    nRasterRows = ds.RasterYSize

    # tile buffer width. Must be bigger then number of pixels in MMU.
    # set buffer width =128 so that size of tile with buffer is a multiple of GDAL GeoTiff block size.
    buffer_width = 128
    if buffer_width < MMU:
        buffer_width = MMU

    # special handling of very small rasters - no need to split in multiple tiles
    if buffer_width >= nRasterCols:
        buffer_width = 0
    if nRasterCols <= BLOCKSIZE or nRasterRows <= BLOCKSIZE:
        buffer_width = 0

    blocksize_with_buffer = BLOCKSIZE + 2 * buffer_width

    # Detected patches with area<MMU will be stored in this list.
    regions_lessMMU = []

    # Exception patches with area<MMU and belonging to exclude class.
    regions_lessMMU_except = []

    nTileCols = int(math.ceil(nRasterCols / BLOCKSIZE))
    nTileRows = int(math.ceil(nRasterRows / BLOCKSIZE))
    last_col = nTileCols - 1
    last_row = nTileRows - 1

    # TILES: ITERATE ROWS
    for tileRow in range(nTileRows):
        if tileRow == 0:
            # first row
            yOff = 0
            yOffInner = 0
            yOffRelative = 0
            block_height = BLOCKSIZE + buffer_width
            block_height_inner = BLOCKSIZE
        else:
            # middle row
            yOff = tileRow * BLOCKSIZE
            yOffInner = yOff + buffer_width
            yOffRelative = buffer_width
            block_height = blocksize_with_buffer
            block_height_inner = BLOCKSIZE

        if tileRow == last_row:
            # special case for last row - adjust block width
            block_height = nRasterRows - yOff
            block_height_inner = block_height - buffer_width

        # if row tile only contains buffer zone and no inner zone, skip..
        if block_height <= buffer_width:
            continue

        # TILES: ITERATE COLUMNS
        for tileCol in range(nTileCols):
            if tileCol == 0:
                # first column
                xOff = 0
                xOffInner = 0
                xOffRelative = 0
                block_width = BLOCKSIZE + buffer_width
                block_width_inner = BLOCKSIZE
            else:
                # middle column
                xOff = tileCol * BLOCKSIZE
                xOffInner = xOff + buffer_width
                xOffRelative = buffer_width
                block_width = blocksize_with_buffer
                block_width_inner = BLOCKSIZE

            if tileCol == last_col:
                # special case for last column - adjust block width
                block_width = nRasterCols - xOff
                block_width_inner = block_width - buffer_width

            # if column tile only contains buffer zone and no inner zone, skip..
            if block_width <= buffer_width:
                continue

            # read inner array (without buffer)
            tile_inner = ds.ReadAsArray(xOffInner, yOffInner, block_width_inner, block_height_inner)

            # special case: if the tile has all values equal then skip MMW checks.
            if tile_inner.min() == tile_inner.max():
                continue

            # reclassify inner tile array if some patches should be grouped together
            if use_reclassify:
                tile_inner = reclassify_values(tile_inner, params["groupcodes"])

            # label the inner array and find patches < MMU
            labels_inner = measure.label(tile_inner, background=NODATA, connectivity=1)
            regions_inner = measure.regionprops(labels_inner)
            regions_inner_lessMMU = [r for r in regions_inner if r.area < MMU]

            # find lessMMU patches inside inner array not touching edge
            regions_lessMMU_edge = [r for r in regions_inner_lessMMU
                                    if r.bbox[0] == 0
                                    or r.bbox[1] == 0
                                    or r.bbox[2] == block_width_inner
                                    or r.bbox[3] == block_height_inner]
            labels_lessMMU_edge = [r.label for r in regions_lessMMU_edge]

            regions_lessMMU_inside = [r for r in regions_inner_lessMMU if r.label not in labels_lessMMU_edge]

            # progress reporting..
            if report_progress:
                msg_tile = "tileRow: {tr}/{ntr} tileCol: {tc} width: {w} height: {h}"
                msg_tile = msg_tile.format(tr=tileRow, ntr=nTileRows, tc=tileCol, w=block_width_inner, h=block_height_inner)
                if len(regions_lessMMU_inside) > 0:
                    print(msg_tile + " found {:d} areas < MMU".format(len(regions_lessMMU_inside), tileRow, tileCol))
                else:
                    print(msg_tile)

            # inspect inner patches
            for r in regions_lessMMU_inside:
                first_coord_x = r.coords[0][0]
                first_coord_y = r.coords[0][1]
                lessMMU_value = tile_inner[first_coord_x, first_coord_y]

                # convert relative coords to absolute. coords are stored as [row, column].
                absolute_coords = [[c[1] + xOffInner, c[0] + yOffInner] for c in r.coords]

                lessMMU_info = {"tileRow": tileRow, "tileCol": tileCol,
                                "area": r.area, "value": lessMMU_value,
                                "coords": absolute_coords}
                if lessMMU_value in exclude_values:
                    regions_lessMMU_except.append(lessMMU_info)
                elif patch_touches_cell_with_value(r.coords, tile_inner, neighbour_exclude_values):
                    regions_lessMMU_except.append(lessMMU_info)
                else:
                    regions_lessMMU.append(lessMMU_info)

            # no need to read-in buffered tile if there are no suspect lessMMU patches at edge of inner tile
            if len(regions_lessMMU_edge) == 0:
                continue

            # read the outer array expanded by buffer with width=number of pixels in MMU
            tile_buffered = ds.ReadAsArray(xOff, yOff, block_width, block_height)

            # reclassify outer tile array if some patches should be grouped together
            if use_reclassify:
                tile_buffered = reclassify_values(tile_buffered, params["groupcodes"])

            labels_buf = measure.label(tile_buffered, background=NODATA, connectivity=1)
            buf_regions = measure.regionprops(labels_buf)
            buf_regions_small = [r for r in buf_regions if r.area < MMU]
            buf_labels_small = [r.label for r in buf_regions_small]

            # edge_regions_small is used for reporting only.
            edge_regions_small = []

            for r in regions_lessMMU_edge:
                first_coord_x = r.coords[0][0]
                first_coord_y = r.coords[0][1]
                val = tile_inner[first_coord_x, first_coord_y]

                # get corresponding value of tile edge patch in buffered array..
                # if the inner tile edge patch has area < MMU also in the expanded tile, report it.
                coord_x_buf = first_coord_x + xOffRelative
                coord_y_buf = first_coord_y + yOffRelative
                lbl_buf = labels_buf[coord_x_buf, coord_y_buf]
                if lbl_buf in buf_labels_small:
                    r_buf = buf_regions[lbl_buf - 1]
                    edge_regions_small.append(r)

                    # coordinates are specified as row, column..
                    # convert [row in tile, column in tile] to [source raster column, source raster row]
                    absolute_coords = [[c[1] + xOff, c[0] + yOff] for c in r_buf.coords]

                    lessMMU_info = {"tileRow": tileRow, "tileCol": tileCol,
                                    "area": r_buf.area, "value": val,
                                    "coords": absolute_coords}

                    if val in exclude_values:
                        regions_lessMMU_except.append(lessMMU_info)
                    elif patch_touches_cell_with_value(r_buf.coords, tile_buffered, neighbour_exclude_values):
                        regions_lessMMU_except.append(lessMMU_info)
                    else:
                        regions_lessMMU.append(lessMMU_info)

            if report_progress and len(edge_regions_small) > 0:
                # report actual edge regions < MMU after applying buffer
                print("xOff {:d} yOff {:d} xOffInner {:d} yOffInner {:d}".format(xOff, yOff, xOffInner, yOffInner))

                msg_tile = "BUFFER: tileRow: {tr}/{ntr} tileCol: {tc} width: {w} height: {h}"
                print(msg_tile.format(tr=tileRow, ntr=nTileRows, tc=tileCol, w=block_width, h=block_height))
                print("found {:d} edge areas < MMU in tile {:d}, {:d}".
                    format(len(edge_regions_small), tileRow, tileCol))

    # FINAL REPORT is saved to a point Shapefile.
    # The shapefile contains one sample point from each lessMMU patch.

    # lessMMU patches belonging to one of exclude_values classes are reported in the exception shapefile.
    if len(regions_lessMMU_except) > 0:
        exceptions_shp_filepath = params["output_dir"].joinpath(params["filepath"].stem + "_lessmmu_exception.shp")
        export_shapefile(regions_lessMMU_except, ds, exceptions_shp_filepath)
        error_zip_filename = zip_shapefile(exceptions_shp_filepath)
        status.add_attachment(error_zip_filename)
        status.add_message("The data source has {:d} exceptional objects under MMU limit of {:d} pixels."
                           .format(len(regions_lessMMU_except), params["area_pixels"]), failed=False)

    # lessMMU patches not belonging to exclude_values are reported in the error shapefile.
    if len(regions_lessMMU) > 0:
        errors_shp_filepath = params["output_dir"].joinpath(params["filepath"].stem + "_lessmmu_error.shp")
        export_shapefile(regions_lessMMU, ds, errors_shp_filepath)
        error_zip_filename = zip_shapefile(errors_shp_filepath)
        status.add_attachment(error_zip_filename)
        status.add_message("The data source has {:d} error objects under MMU limit of {:d} pixels."
                           .format(len(regions_lessMMU), params["area_pixels"]))
        return
