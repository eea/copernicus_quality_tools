import math
import os
import subprocess

DESCRIPTION = "Minimum mapping unit."
IS_SYSTEM = False

MAX_REPORTED_REGION_COUNT = 1000000


def write_percent(percent_filepath, percent):
    percent_filepath.write_text(str(percent))

def write_progress(progress_filepath, message):
    with open(str(progress_filepath), "a") as f:
        f.write(message + "\n")

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
    import numpy

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

def patch_touches_raster_edge(coordinates, raster_nrows, raster_ncols):
    """
    Takes a list of [row, column] cell coordinates and inspects if at least one of the coordinates
    is located exactly at the specified edge of the tile.
    This function can be used for detecting patches touching the raster bounding box.
    :param coordinates: The patch of same-value raster cells.
    :param raster_nrows: Number of rows in the whole source raster.
    :param raster_ncols: Number of columns in the whole source raster.
    :return: True if at least one cell in the patch is located at source raster edge.
    """
    for coor in coordinates:
        if coor[0] == 0 or coor[1] == 0 or coor[0] == raster_ncols - 1 or coor[1] == raster_nrows - 1:
            return True
    return False


def export(regions, raster_ds, gpkg_filepath, max_regions_count):
    """
    Exports a list of lessMMU region dictionaries to geopackage.
    :param regions: list of dicts with {"coords", "area", "value"}
    :param raster_ds: original raster dataset
    :param gpkg_filepath: filepath the vector datasource is to be exported to
    :param max_regions_count: maximum number of regions to be exported.
    """
    import osgeo.ogr as ogr
    import osgeo.osr as osr

    if len(regions) > 0:

        (upper_left_x, x_size, x_rotation, upper_left_y, y_rotation, y_size) = raster_ds.GetGeoTransform()

        srs = osr.SpatialReference()
        srs.ImportFromWkt(raster_ds.GetProjection())

        driver = ogr.GetDriverByName("GPKG")
        shapeData = driver.CreateDataSource(str(gpkg_filepath))

        layer = shapeData.CreateLayer('ogr_pts', srs, ogr.wkbPoint)
        areaField = ogr.FieldDefn("area_px", ogr.OFTInteger)
        layer.CreateField(areaField)
        valueField = ogr.FieldDefn("value", ogr.OFTInteger)
        layer.CreateField(valueField)

        layerDefinition = layer.GetLayerDefn()

        i = 0
        for rInfo in regions:

            if i > max_regions_count:
                break

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

def get_neighbouring_tiles(boundary_source, aoi_code):
    """
    Get list of aoi codes of neighbouring tiles
    :param boundary_source: Boundary source file path.
    :param aoi_code: Aoi code of the processed tile.
    :return: List of aoi codes of neighbouring tiles.

    """
    import osgeo.ogr as ogr

    neighbour_aoi_codes = list()

    # try:
    aoi_code = aoi_code.lower()

    # read the boundary source, get the geometry of the processed tile
    boundary_ds = ogr.Open(boundary_source)
    boundary_lyr = boundary_ds.GetLayer()

    boundary_lyr.SetAttributeFilter("aoi_code = '{aoi_code}'".format(aoi_code=aoi_code))
    if boundary_lyr.GetFeatureCount() < 1:
        return neighbour_aoi_codes

    tile_feature = boundary_lyr.GetNextFeature()
    tile_geom = tile_feature.GetGeometryRef()
    tile_geom_buffered = tile_geom.Buffer(1)

    boundary_ds, boundary_lyr, tile_feature = None, None, None

    # read the boundary source again, select neighbouring tiles using buffered geometry of the processed tile

    boundary_ds = ogr.Open(boundary_source)
    boundary_lyr = boundary_ds.GetLayer()

    boundary_lyr.SetSpatialFilter(tile_geom_buffered)
    tile_feature = boundary_lyr.GetNextFeature()
    while tile_feature is not None:
        neighbour_aoi_code = tile_feature.GetField("aoi_code")
        if neighbour_aoi_code == aoi_code:
            tile_feature = boundary_lyr.GetNextFeature()
        else:
            neighbour_aoi_codes.append(neighbour_aoi_code)
            tile_feature = boundary_lyr.GetNextFeature()
    return neighbour_aoi_codes
    # except:
    #     return neighbour_aoi_codes

def raster_extend_shifted(raster_file_path, mmu):
    """
    Get extent of the input raster shifted by mmu
    :param raster_file_path: Input raster file path.
    :param mmu: Minimum mapping unit (in pixels).
    :return: MMU-shifted raster extend (minx, miny, maxx, maxy]).
    """
    import osgeo.gdal as gdal
    rf_ds = gdal.Open(raster_file_path)
    geoTransform = rf_ds.GetGeoTransform()
    raster_xsize, raster_ysize = rf_ds.RasterXSize, rf_ds.RasterYSize
    minx, maxy = geoTransform[0], geoTransform[3]
    pixel_xsize, pixel_ysize = geoTransform[1], geoTransform[5]
    mmu_xshift = mmu * pixel_xsize
    mmu_yshift = mmu * pixel_ysize
    maxx = minx + (pixel_xsize * raster_xsize) + mmu_xshift
    miny = maxy + pixel_ysize * raster_ysize + mmu_yshift
    minx = minx - mmu_xshift
    maxy = maxy - mmu_yshift
    rf_ds = None
    return [minx, miny, maxx, maxy]


def run_check(params, status):
    import osgeo.gdal as gdal
    import osgeo.ogr as ogr
    import skimage.measure as measure
    from pathlib import Path
    from copy import deepcopy

    from qc_tool.raster.helper import do_raster_layers
    from qc_tool.vector.helper import do_s3_download

    # set this to true for reporting partial progress to a _progress.txt file.
    report_progress = True

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
        NODATA = -1  # FIXME use a value that is outside of the range of possible raster values.

    # The optional report_exceptions parameter indicates whether any exceptions should be reported.
    report_exceptions = params.get("report_exceptions", False)

    # size of a raster tile. Should be a multiple of 256 because GeoTiff stores its data in 256*256 pixel blocks.
    BLOCKSIZE = 2048
    MMU = params["area_pixels"]

    # Some classes can optionally be excluded from MMU requirements.
    # Pixels belonging to these classes are reported as exceptions.
    if "value_exception_codes" in params:
        exclude_values = params["value_exception_codes"]
    else:
        exclude_values = []

    # neighbouring values to exclude.
    # patches with area < MMU which touch a patch having class in neighbour_exclude_values are reported
    # as exceptions.
    if "neighbour_exception_codes" in params:
        neighbour_exclude_values = params["neighbour_exception_codes"]
    else:
        neighbour_exclude_values = []

    # Get layer definitions dictionary for further MMU-check processing...
    layer_defs = deepcopy(do_raster_layers(params))

    # The optional 'check_neighbours' parameter indicates whether to check MMU rules also on raster borders using neighbouring tiles.
    # If 'check_neighbours' parameter is True, then also 'boundary_source' optional parameter has to be set.
    check_neighbours = params.get("check_neighbours", False)
    if check_neighbours:
        if "boundary_source" in params:
            boundary_source = params["boundary_source"]
        else:
            status.aborted("If the optional parameter 'check_neighbours' is turned on, "
                          "the optional parameter 'boundary_source' must also be set.")
            return

        # find absolute path to the boundary source file
        if boundary_source.endswith(".gpkg") or boundary_source.endswith(".shp"):
            boundary_source_filepath = params["boundary_dir"].joinpath("vector", boundary_source)
            if not boundary_source_filepath.exists():
                status.aborted("Boundary source '{bs}' does not exist.".format(bs=str(boundary_source_filepath)))
                return
        else:
            status.aborted("Boundary source file must be either GEOPACKAGE (.gpkg) or ESRI SHAPEFILE (.shp). "
                           "Specified boundary source: '{bs}.'".format(bs=str(boundary_source)))
            return
        neighbouring_tiles_aoi_codes = get_neighbouring_tiles(str(boundary_source_filepath), params["aoi_code"])

        # download deliveries for the neighbouring tiles
        raster_path_orig = params['raster_layer_defs']['raster']['src_filepath'].as_posix()
        s3_local_filepaths = [raster_path_orig]
        s3_local_dir = params["unzip_dir"].joinpath("neighbours")
        for neighbouring_tile_aoi_code in neighbouring_tiles_aoi_codes:

            key_prefix = params["s3"]["key_prefix"].replace(params["aoi_code"].upper(), neighbouring_tile_aoi_code.upper()) # TODO: osetrit lower/upper case nejak obecne!!!

            # osetrit chybu stazeni jednoho nebo vice ze sousednich tilu -> status.failed

            do_s3_download(params["s3"]["host"],
                           params["s3"]["access_key"],
                           params["s3"]["secret_key"],
                           params["s3"]["bucketname"],
                           key_prefix,
                           s3_local_dir,
                           status)
        s3_local_filepaths += [os.path.join(s3_local_dir, s3_local_filename) for s3_local_filename in os.listdir(s3_local_dir)]
        # create VRT mosaic
        mosaic_path_vrt = raster_path_orig.replace('.tif', '.vrt')
        gdal.BuildVRT(mosaic_path_vrt, s3_local_filepaths)

        # clip the mosaic with MMU-extended original tile footprint
        re_shft = raster_extend_shifted(raster_path_orig, MMU + 1)
        raster_path_extended = raster_path_orig.replace(".tif", "_mmushift.tif")
        warp_cmd = ["gdalwarp", "-te", str(re_shft[0]), str(re_shft[1]), str(re_shft[2]), str(re_shft[3]),
                    "-co", "COMPRESS=DEFLATE", mosaic_path_vrt, raster_path_extended]
        subprocess.check_output(warp_cmd)

        # update layer defs to check the MMU on the extended raster file
        raster_path_extended = Path(raster_path_extended)
        layer_defs[0]["src_filepath"] = raster_path_extended
        layer_defs[0]["src_layer_name"] = raster_path_extended.name

    for layer_def in layer_defs:

        progress_filename = "{:s}_{:s}_progress.txt".format(__name__.split(".")[-1], layer_def["src_filepath"].stem)
        progress_filepath = params["output_dir"].joinpath(progress_filename)
        percent_filename = "{:s}_{:s}_percent.txt".format(__name__.split(".")[-1], layer_def["src_filepath"].stem)
        percent_filepath = params["output_dir"].joinpath(percent_filename)

        # The checked raster is not read into memory as a whole. Instead it is read in tiles.
        # Instead, ReadAsArray is used to read subsets of the raster (tiles) on demand.
        ds = gdal.Open(str(layer_def["src_filepath"]))

        nRasterCols = ds.RasterXSize
        nRasterRows = ds.RasterYSize

        # tile buffer width. Must be bigger then number of pixels in MMU.
        buffer_width = MMU + 1

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

        if report_progress:
            msg = "processing {:d} tiles: {:d} rows, {:d} columns".format(nTileRows * nTileCols, nTileRows, nTileCols)
            write_progress(progress_filepath, msg)

        # TILES: ITERATE ROWS
        for tileRow in range(nTileRows):

            if report_progress:
                progress_percent = int(100 *((tileRow + 1) / nTileRows))
                write_percent(percent_filepath, progress_percent)

            if tileRow == 0:
                # First row
                yOff = 0
                yOffInner = 0
                yOffRelative = 0
                block_height = BLOCKSIZE + buffer_width
                block_height_inner = BLOCKSIZE
            else:
                # Middle row
                yOff = tileRow * BLOCKSIZE
                yOffInner = yOff + buffer_width
                yOffRelative = buffer_width
                block_height = blocksize_with_buffer
                block_height_inner = BLOCKSIZE

            if tileRow == last_row:
                # Last row is a special case - block width must be adjusted.
                block_height = nRasterRows - yOff
                block_height_inner = block_height - buffer_width

            # if row tile only contains buffer zone and no inner zone, skip..
            if block_height <= buffer_width:
                continue

            # if we reached the maximum number of patches < MMU, then report message and exit.
            if len(regions_lessMMU) > MAX_REPORTED_REGION_COUNT:
                break

            # TILES: ITERATE COLUMNS
            for tileCol in range(nTileCols):
                if tileCol == 0:
                    # First column
                    xOff = 0
                    xOffInner = 0
                    xOffRelative = 0
                    block_width = BLOCKSIZE + buffer_width
                    block_width_inner = BLOCKSIZE
                else:
                    # Middle column
                    xOff = tileCol * BLOCKSIZE
                    xOffInner = xOff + buffer_width
                    xOffRelative = buffer_width
                    block_width = blocksize_with_buffer
                    block_width_inner = BLOCKSIZE

                if tileCol == last_col:
                    # Last column is a special case - block width must be adjusted.
                    block_width = nRasterCols - xOff
                    block_width_inner = block_width - buffer_width

                # if column tile only contains buffer zone and no inner zone, skip..
                if block_width <= buffer_width:
                    continue

                # if we reached the maximum number of patches < MMU, then report message and exit.
                if len(regions_lessMMU) > MAX_REPORTED_REGION_COUNT:
                    break

                # read whole array (with buffers)
                tile_buffered = ds.ReadAsArray(xOff, yOff, block_width, block_height)

                # special case: if the tile has all values equal then skip MMU checks.
                if tile_buffered.min() == tile_buffered.max():
                    if report_progress:
                        msg_tile = "tileRow: {tr}/{ntr} tileCol: {tc} width: {w} height: {h} all values same."
                        msg_tile = msg_tile.format(tr=tileRow, ntr=nTileRows, tc=tileCol, w=block_width_inner,
                                                   h=block_height_inner)
                        write_progress(progress_filepath, msg_tile)
                    continue

                # reclassify inner tile array if some patches should be grouped together
                if use_reclassify:
                    # tile_inner = reclassify_values(tile_inner, params["groupcodes"])
                    tile_buffered = reclassify_values(tile_buffered, params["groupcodes"])

                # inner tile is subset of buffered tile
                tile_inner = tile_buffered[yOffRelative: yOffRelative + block_height_inner, xOffRelative: xOffRelative + block_width_inner]

                # read inner array (without buffer)

                # label the inner array and find patches < MMU
                labels_inner = measure.label(tile_inner, background=NODATA, connectivity=1)
                regions_inner = measure.regionprops(labels_inner)
                regions_inner_lessMMU = [r for r in regions_inner if r.area < MMU]

                regions_lessMMU_edge = [r for r in regions_inner_lessMMU
                                        if r.bbox[0] == 0
                                        or r.bbox[1] == 0
                                        or r.bbox[3] == block_width_inner
                                        or r.bbox[2] == block_height_inner]

                labels_lessMMU_edge = [r.label for r in regions_lessMMU_edge]

                regions_lessMMU_inside = [r for r in regions_inner_lessMMU if r.label not in labels_lessMMU_edge]


                # progress reporting..
                if report_progress:
                    msg = "tileRow: {tr}/{ntr} tileCol: {tc} width: {w} height: {h}"
                    msg = msg.format(tr=tileRow, ntr=nTileRows, tc=tileCol, w=block_width_inner, h=block_height_inner)
                    if len(regions_lessMMU_inside) > 0:
                        msg += " found {:d} areas < MMU".format(len(regions_lessMMU_inside), tileRow, tileCol)
                    write_progress(progress_filepath, msg)

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
                        if report_exceptions:
                            regions_lessMMU_except.append(lessMMU_info)
                    elif patch_touches_cell_with_value(r.coords, tile_inner, neighbour_exclude_values):
                        if report_exceptions:
                            regions_lessMMU_except.append(lessMMU_info)
                    elif patch_touches_raster_edge(absolute_coords, nRasterRows, nRasterCols):
                        if report_exceptions:
                            regions_lessMMU_except.append(lessMMU_info)
                    else:
                        regions_lessMMU.append(lessMMU_info)

                # no need to read-in buffered tile if there are no suspect lessMMU patches at edge of inner tile
                if len(regions_lessMMU_edge) == 0:
                    continue
                elif report_progress:
                    msg = "tileRow: {tr}/{ntr} tileCol: {tc} width: {w} height: {h} INSPECTING EDGE PATCHES"
                    msg = msg.format(tr=tileRow, ntr=nTileRows, tc=tileCol, w=block_width, h=block_height)
                    write_progress(progress_filepath, msg)

                # processing the outer array expanded by buffer with width=number of pixels in MMU

                # optimization: set pixels not within buffer zone (deep inside outer array) to background.
                optimization = True
                if optimization:
                    inner_buf_startcol = xOffRelative + MMU
                    inner_buf_startrow = yOffRelative + MMU
                    inner_buf_endcol = xOffRelative + block_width_inner - MMU
                    inner_buf_endrow = yOffRelative + block_height_inner - MMU
                    if inner_buf_endcol > inner_buf_startcol and inner_buf_endrow > inner_buf_startrow:
                        tile_buffered[inner_buf_startrow:inner_buf_endrow,
                                      inner_buf_startcol:inner_buf_endcol] = NODATA

                labels_buf = measure.label(tile_buffered, background=NODATA, connectivity=1)
                buf_regions = measure.regionprops(labels_buf)
                buf_regions_small = [r for r in buf_regions if r.area < MMU]
                buf_labels_small = [r.label for r in buf_regions_small]

                # edge_regions_small is used for reporting only.
                edge_regions_small = []

                for r in regions_lessMMU_edge:

                    first_coord_row = r.coords[0][0]
                    first_coord_col = r.coords[0][1]

                    val = tile_inner[first_coord_row, first_coord_col]

                    # get corresponding value of tile edge patch in buffered array..
                    # if the inner tile edge patch has area < MMU also in the expanded tile, report it.
                    coord_row_buf = first_coord_row + yOffRelative
                    coord_col_buf = first_coord_col + xOffRelative

                    #lbl_buf = labels_buf[coord_x_buf, coord_y_buf]
                    lbl_buf = labels_buf[coord_row_buf, coord_col_buf]
                    if lbl_buf in buf_labels_small:
                        r_buf = buf_regions[lbl_buf - 1]
                        edge_regions_small.append(r)

                        # coordinates are specified as row, column..
                        # convert [row in tile, column in tile] to [source raster column, source raster row]
                        absolute_coords = [[c[1] + xOff, c[0] + yOff] for c in r_buf.coords]

                        lessMMU_info = {"tileRow": tileRow, "tileCol": tileCol,
                                        "area": r_buf.area, "value": val,
                                        "coords": absolute_coords}

                        # handling special cases (exception patches)
                        if val in exclude_values:
                            if report_exceptions:
                                regions_lessMMU_except.append(lessMMU_info)
                        elif patch_touches_cell_with_value(r_buf.coords, tile_buffered, neighbour_exclude_values):
                            if report_exceptions:
                                regions_lessMMU_except.append(lessMMU_info)
                        elif patch_touches_raster_edge(absolute_coords, nRasterRows, nRasterCols):
                            if report_exceptions:
                                regions_lessMMU_except.append(lessMMU_info)
                        else:
                            regions_lessMMU.append(lessMMU_info)

                if report_progress and len(edge_regions_small) > 0:
                    # report actual edge regions < MMU after applying buffer
                    msg = "xOff {:d} yOff {:d} xOffInner {:d} yOffInner {:d}".format(xOff, yOff, xOffInner, yOffInner)
                    write_progress(progress_filepath, msg)
                    msg = "BUFFER: tileRow: {tr}/{ntr} tileCol: {tc} width: {w} height: {h}"
                    msg = msg.format(tr=tileRow, ntr=nTileRows, tc=tileCol, w=block_width, h=block_height)
                    num_edge_patches = len(edge_regions_small)
                    msg += " found {:d} edge areas < MMU in tile {:d}, {:d}".format(num_edge_patches, tileRow, tileCol)
                    write_progress(progress_filepath, msg)

        # Export errors and exceptions to geopackage.
        # The geopackage contains one sample point from each lessMMU patch.

        ## lessMMU patches belonging to one of exclude_values classes are reported as exceptions.
        if report_exceptions and len(regions_lessMMU_except) > 0:
            gpkg_filename = "s{:02d}_{:s}_lessmmu_exception.gpkg".format(params["step_nr"], layer_def["src_filepath"].stem)
            gpkg_filepath = params["output_dir"].joinpath(gpkg_filename)
            export(regions_lessMMU_except, ds, gpkg_filepath, MAX_REPORTED_REGION_COUNT)
            status.add_attachment(gpkg_filename)
            if len(regions_lessMMU_except) <= MAX_REPORTED_REGION_COUNT:
                status.info("The data source has {:d} exceptional objects under MMU limit of {:d} pixels."
                            .format(len(regions_lessMMU_except), params["area_pixels"]))
            else:
                status.info("The data source has more than {:d} exceptional objects under MMU limit of {:d} pixels."
                            .format(MAX_REPORTED_REGION_COUNT, params["area_pixels"]))

        ## lessMMU patches not belonging to exclude_values are reported as errors.
        if len(regions_lessMMU) > 0:
            gpkg_filename = "s{:02d}_{:s}_lessmmu_error.gpkg".format(params["step_nr"], layer_def["src_filepath"].stem)
            gpkg_filepath = params["output_dir"].joinpath(gpkg_filename)
            export(regions_lessMMU, ds, gpkg_filepath, MAX_REPORTED_REGION_COUNT)
            status.add_attachment(gpkg_filename)
            if len(regions_lessMMU) <= MAX_REPORTED_REGION_COUNT:
                status.failed("The data source has {:d} error objects under MMU limit of {:d} pixels."
                              .format(len(regions_lessMMU), params["area_pixels"]))
            else:
                status.failed("The data source has more than {:d} error objects under MMU limit of {:d} pixels."
                              .format(MAX_REPORTED_REGION_COUNT, params["area_pixels"]))