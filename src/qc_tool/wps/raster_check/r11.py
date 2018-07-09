#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Minimum mapping unit check.
"""

import subprocess

from osgeo import ogr

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params):
    """
    Minimum mapping unit (MMU) check.
    :param params: configuration
    :return: status + message
    """

    # convert mmu limit from 'ha' to 'pix' (expected pixel size of 20m)
    # mmu_limit = int(ceil(params["area_ha"]*25))
    # for example 20x20 pixel and 5ha mmu -> 125 pixels mmu_limit

    lessmmu_shp_path = params["output_dir"].joinpath("lessmmu_areas.shp")

    GRASS_VERSION = "grass72"

    # (1) create a new GRASS location named "location" in the job directory
    location_path = params["tmp_dir"].joinpath("location")
    p1 = subprocess.run([GRASS_VERSION,
             "-c",
             str(params["filepath"]),
             "-e",
             str(location_path)], check=True)
    if p1.returncode != 0:
        return {"status": "failed", "messages": ["GRASS GIS error: cannot create location!"]}

    # (2) import the data into a GRASS mapset named PERMANENT
    mapset_path = location_path.joinpath("PERMANENT")
    p2 = subprocess.run(["grass72",
              str(mapset_path),
              "--exec",
              "r.in.gdal",
                         "input={:s}".format(str(params["filepath"])),
              "output=inpfile"],
             check=True)
    if p2.returncode != 0:
        return {"status": "failed", "messages": ["GRASS GIS error: cannot import raster from {:s}".format(params["filepath"].name)]}

    # (3) run r.reclass.area (area is already in hectares)
    mmu_limit_ha = params["area_ha"]
    p3 = subprocess.run([GRASS_VERSION,
              str(mapset_path),
              "--exec",
              "r.reclass.area",
              "--verbose",
              "input=inpfile",
              "output=lessmmu_raster",
              "value={:f}".format(mmu_limit_ha),
              "mode=lesser",
              "method=reclass"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    if "No areas of size less than or equal to" in str(p3.stdout):
        return {"status": "ok"}

    elif p3.returncode != 0:
        return {"status": "failed", "messages": ["GRASS GIS error in r.reclass.area"]}

    # (4) run r.to.vect: convert clumps with mmu < mmu_limit_ha to polygon areas
    p4 = subprocess.run([GRASS_VERSION,
              str(mapset_path),
              "--exec",
              "r.to.vect",
              "--overwrite",
              "--verbose",
              "-s",
              "-v",
              "type=area",
              "input=lessmmu_raster",
              "output=lessmmu_areas"],
             check=True)
    if p4.returncode != 0:
        return {"status": "failed", "messages": ["GRASS GIS error in r.to.vect"]}

    # (5) export lessmmu_areas to shapefile
    p5 = subprocess.run([GRASS_VERSION,
              str(mapset_path),
              "--exec",
              "v.out.ogr",
              "input=lessmmu_areas",
              "output={:s}".format(str(lessmmu_shp_path)),
              "format=ESRI_Shapefile"],
             check=True)
    if p5.returncode != 0:
        return {"status": "failed", "messages": ["GRASS GIS error in executing v.out.ogr"]}

    if not lessmmu_shp_path.exists():
        return {"status": "failed",
                "messages": ["GRASS GIS error. exported lessmmu_areas shapefile {:s} does not exist.".format(str(lessmmu_shp_path))]}

    ogr.UseExceptions()
    try:
        ds_lessmmu = ogr.Open(str(lessmmu_shp_path))
        if ds_lessmmu is None:
            return {"status": "failed",
                    "messages": ["GRASS GIS error or OGR error. The file {:s} can not be opened.".format(str(lessmmu_shp_path))]}
    except BaseException as e:
        return {"status": "failed",
                "messages": ["GRASS GIS error or OGR error."
                             " The shapefile {:s} cannot be opened."
                             " Exception: {:s}".format(str(lessmmu_shp_path, str(e)))]}

    lyr = ds_lessmmu.GetLayer()
    lessmmu_count = lyr.GetFeatureCount()

    if lessmmu_count == 0:
        result = {"status": "ok"}
    else:
        result = {"status": "failed",
                  "messages": ["The data source has {:s} objects under MMU limit"
                               " of {:s} ha.".format(str(lessmmu_count), str(params["area_ha"]))]}
    return result
