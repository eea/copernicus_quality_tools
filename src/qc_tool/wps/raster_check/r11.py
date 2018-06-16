#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Minimum mapping unit check.
"""

from pathlib import Path
from subprocess import run

from osgeo import ogr

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__, "Minimum mapping unit check.")
def run_check(filepath, params):
    """
    Minimum mapping unit (MMU) check.
    :param filepath: pathname to data source
    :param params: configuration
    :return: status + message
    """

    # convert mmu limit from 'ha' to 'pix' (expected pixel size of 20m)
    # mmu_limit = int(ceil(params["area_ha"]*25))
    # for example 20x20 pixel and 5ha mmu -> 125 pixels mmu_limit

    job_dir = params["job_dir"]

    lessmmu_shp_path = Path(job_dir, "lessmmu_areas.shp")

    GRASS_VERSION = "grass72"

    # (1) create a new GRASS location named "location" in the job directory
    location_path = Path(job_dir, "location")
    p1 = run([GRASS_VERSION,
             "-c",
             filepath,
             "-e",
             str(location_path)], check=True)
    if p1.returncode != 0:
        return {"status": "failed", "message": "GRASS GIS error: cannot create location!"}

    # (2) import the data into a GRASS mapset named PERMANENT
    mapset_path = Path(location_path, "PERMANENT")
    p2 = run(["grass72",
              str(mapset_path),
              "--exec",
              "r.in.gdal",
              "input={:s}".format(filepath),
              "output=inpfile"],
             check=True)
    if p2.returncode != 0:
        return {"status": "failed", "message": "GRASS GIS error: cannot import raster from {:s}".format(filepath)}

    # (3) run r.reclass.area (area is already in hectares)
    mmu_limit_ha = params["area_ha"]
    p3 = run([GRASS_VERSION,
              str(mapset_path),
              "--exec",
              "r.reclass.area",
              "--verbose",
              "input=inpfile",
              "output=lessmmu_raster",
              "value={:f}".format(mmu_limit_ha),
              "mode=lesser",
              "method=reclass"],
             check=True)
    if p3.returncode != 0:
        return {"status": "failed", "message": "GRASS GIS error in r.reclass.area"}

    # (4) run r.to.vect: convert clumps with mmu < mmu_limit_ha to polygon areas
    p4 = run([GRASS_VERSION,
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
        return {"status": "failed", "message": "GRASS GIS error in r.to.vect"}

    # (5) export lessmmu_areas to shapefile
    p5 = run([GRASS_VERSION,
              str(mapset_path),
              "--exec",
              "v.out.ogr",
              "input=lessmmu_areas",
              "output={:s}".format(str(lessmmu_shp_path)),
              "format=ESRI_Shapefile"],
             check=True)
    if p5.returncode != 0:
        return {"status": "failed", "message": "GRASS GIS error in executing v.out.ogr"}

    if not lessmmu_shp_path.exists():
        return {"status": "failed",
                "message": "GRASS GIS error. exported lessmmu_areas shapefile {:s} does not exist.".format(str(lessmmu_shp_path))}

    ogr.UseExceptions()
    try:
        ds_lessmmu = ogr.Open(str(lessmmu_shp_path))
        if ds_lessmmu is None:
            return {"status": "failed",
                    "message": "GRASS GIS error or OGR error. The file {:s} can not be opened.".format(str(lessmmu_shp_path))}
    except BaseException as e:
        return {"status": "failed",
                "message": "GRASS GIS error or OGR error. The shapefile {:s} cannot be opened. Exception: {:s}".format(
                    str(lessmmu_shp_path, str(e)))}

    lyr = ds_lessmmu.GetLayer()
    lessmmu_count = lyr.GetFeatureCount()

    if lessmmu_count == 0:
        result = {"status": "ok"}
    else:
        result = {"status": "failed",
                "message": "The data source has {:s} objects under MMU limit of {:s} ha.".format(str(lessmmu_count),
                                                                                                 str(params["area_ha"]))}
    return result
