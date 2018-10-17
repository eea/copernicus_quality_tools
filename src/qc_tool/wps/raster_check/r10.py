#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from pathlib import Path
import numpy
from osgeo import gdal
from osgeo import ogr
from osgeo import osr

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):

    # get countrycode from filename
    filename = params["filepath"].name.lower()

    country_code = params["country_code"]
    print("country_code: {:s}".format(country_code))

    # get raster resolution from the raster file
    ds = gdal.Open(str(params["filepath"]))
    # get raster pixel size
    gt = ds.GetGeoTransform()
    resolution = abs(gt[1])

    # Find the external boundary raster mask layer.
    raster_boundary_dir = params["boundary_dir"].joinpath("raster")
    mask_file = raster_boundary_dir.joinpath("mask_{:03d}m_{:s}.tif".format(resolution, country_code))
    print(mask_file)
    return

    # FIXME we need to work with a boundary raster mask.
    # the code below needs to be rewritten.
    boundary_filepaths = [path for path in bdir.glob("**/boundary_{:s}.shp".format(country_code)) if path.is_file()]
    if len(boundary_filepaths) == 0:
        status.aborted()
        status.add_message(
            "Can not find boundary for country {:s} under directory {:s}.".format(country_code, str(bdir)))
        return
    if len(boundary_filepaths) > 1:
        status.aborted()
        status.add_message("More than one boundary found for country {:s}: {:s}.".format(country_code, ", ".join(
            str(p) for p in boundary_filepaths)))
        return
    #layer_defs["boundary"] = {"src_filepath": boundary_filepaths[0], "src_layer_name": boundary_filepaths[0].stem}

    boundary_filepath = boundary_filepaths[0]
    boundary_ds = ogr.Open(str(boundary_filepath))
    if boundary_ds is None:
        status.aborted()
        status.add_message("Boundary file {:s} for country {:s} has incorrect file format and cannot be opened.".format(
            boundary_filepath.name, country_code
        ))

    # ma_ds = ogr.Open(params["mapped_area"])
    boundary_poly = ogr.Geometry(ogr.wkbMultiPolygon)
    boundary_layer = boundary_ds.GetLayer()

    for idx, feat in enumerate(boundary_layer):
        if feat.GetField("CNTR_ID").lower() == country_code:
            boundary_poly.AddGeometry(feat.GetGeometryRef().Clone())

    boundary_ft = [ft for ft in boundary_layer if ft.GetField("CNTR_ID").lower() == country_code]
    ma_geom = boundary_ft.GetGeometryRef()

    multipol = ogr.Geometry(ogr.wkbMultiPolygon)
    for feat in boundary_ft:
        poly = feat.GetGeometryRef()
        if poly:
            multipol.AddGeometry(feat.GetGeometryRef().Clone())

    # open raster data source
    ras_ds = gdal.Open(str(params["filepath"]))

    # transform mapped_area geometry into raster SRS
    source_sr = boundary_layer.GetSpatialRef()
    target_sr = osr.SpatialReference()
    target_sr.ImportFromWkt(ras_ds.GetProjectionRef())
    coordTrans = osr.CoordinateTransformation(source_sr, target_sr)
    ma_geom.Transform(coordTrans)

    # load raster band, get NoData value
    ras_band = ras_ds.GetRasterBand(1)
    NoData = ras_band.GetNoDataValue()
    ras_band.DeleteNoDataValue()

    # Get raster info
    transform = ras_ds.GetGeoTransform()

    # get coordinates of upper left corner of input raster
    ULX = transform[0]
    ULY = transform[3]

    # get pixel size
    pixelWidth = transform[1]
    pixelHeight = transform[5]

    # in case of geometry of multipolygon type
    if ma_geom.GetGeometryName() == 'MULTIPOLYGON':

        # prepare lists for x,y coordinates of polygon vertexes
        pointsX = []
        pointsY = []

        # browse through multipart geometry
        for i in range(0, ma_geom.GetGeometryCount()):
            geomSingle = ma_geom.GetGeometryRef(i)

            ring = geomSingle.GetGeometryRef(0)

            # browse through polygons and write x,y coordinates of vertexes to lists
            for p in range(ring.GetPointCount()):
                x, y, z = ring.GetPoint(p)
                pointsX.append(x)
                pointsY.append(y)

    elif ma_geom.GetGeometryName() == 'POLYGON':

        # prepare lists for x,y coordinates of polygon vertexes
        pointsX = []
        pointsY = []

        ring = ma_geom.GetGeometryRef(0)

        # browse through polygons and write x,y coordinates of vertexes to list
        for p in range(ring.GetPointCount()):
            x, y, z = ring.GetPoint(p)
            pointsX.append(x)
            pointsY.append(y)

    # get coordinates of polygons bounding box
    Xmin = min(pointsX)
    Xmax = max(pointsX)
    Ymin = min(pointsY)
    Ymax = max(pointsY)

    # prepare pixel coordinates of upper left corner of bounding box and it's pixel size
    Xoff = int((Xmin - ULX) / pixelWidth)
    Yoff = int((ULY - Ymax) / pixelWidth)
    xcount = int((Xmax - Xmin) / pixelWidth) + 1
    ycount = int((Ymax - Ymin) / pixelWidth) + 1

    # Create memory target raster
    target_ds = gdal.GetDriverByName('MEM').Create('', xcount, ycount, 1, gdal.GDT_Byte)
    target_ds.SetGeoTransform((Xmin, pixelWidth, 0, Ymax, 0, pixelHeight))

    # Rasterize polygon geometry
    rast_ogr_ds = ogr.GetDriverByName('Memory').CreateDataSource('wrk')
    rast_mem_lyr = rast_ogr_ds.CreateLayer('poly', srs=target_sr)

    feat = ogr.Feature(rast_mem_lyr.GetLayerDefn())
    feat.SetGeometry(ma_geom)
    rast_mem_lyr.CreateFeature(feat)
    gdal.RasterizeLayer(target_ds, [1], rast_mem_lyr, burn_values=[1], options=["ALL_TOUCHED=True"])

    # check if bounding box is within the input raster
    if (0 <= Xoff and (Xoff + xcount) <= ras_band.XSize) and (
                    0 <= Yoff and (Yoff + ycount) <= ras_band.YSize):
        srcRasterArray = ras_band.ReadAsArray(Xoff, Yoff, xcount, ycount).astype(numpy.int)

        # read mask (bounding box raster) as array
        mask = target_ds.GetRasterBand(1)
        maskArray = mask.ReadAsArray(0, 0, xcount, ycount).astype(numpy.int)
        maskArray = numpy.logical_not(maskArray)

        # Mask zone of raster and fill gaps by 9999
        zonearray = numpy.ma.masked_array(srcRasterArray, maskArray).astype(int)

        if NoData in zonearray:
            status.add_message("NoData pixels occured in mapped area.")
            return
        else:
            return
