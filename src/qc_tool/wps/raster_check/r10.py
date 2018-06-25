#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
NoData pixels check.
"""

import numpy
import re

from osgeo import gdal
from osgeo import osr
from osgeo import ogr
from pathlib import Path

# from qc_tool.wps.registry import register_check_function


# @register_check_function(__name__, "In the mapped area are no NoData pixels.")
def run_check(filepath, params):
    """
    NoData pixels check.
    :param filepath: pathname to data source
    :param params: configuration
    :return: status + message
    """

    # get countrycode from filename
    filename = Path(filepath).name.lower()
    countrycode = re.search(params["file_name_regex"], filename).group(1)

    # get geometry on mapped area
    ma_ds = ogr.Open(params["mapped_area"])
    ma_lyr = ma_ds.GetLayer()
    ma_ft = [ft for ft in ma_lyr if ft.GetField("iso_code") == countrycode][0]
    ma_geom = ma_ft.GetGeometryRef()

    # open raster data source
    ras_ds = gdal.Open(filepath)

    # transform mapped_area geometry into raster SRS
    source_sr = ma_lyr.GetSpatialRef()
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

        numpy.set_printoptions(threshold=numpy.nan)
        # TODO: vraci prazne zonalni pole...
        if NoData in zonearray:
            return {"status": "failed",
                    "message": "NoData pixels occured in mapped area."}
        else:
            return {"status": "ok"}


f = "/home/jiri/Plocha/COPQC_HRLDATA/FTY_2015_100m_eu_03035_d02_E30N20/FTY_2015_100m_eu_03035_d02_E30N20_clip.TIF"
p = {"mapped_area": "/home/jiri/Plocha/COPQC_HRLDATA/test_polygon.shp",
     "file_name_regex": "^fty_[0-9]{4}_100m_(.+?)_[0-9]{5}.*.tif$$"}
print run_check(f, p)

