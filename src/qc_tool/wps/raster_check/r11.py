#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Minimum mapping unit check.
"""

import subprocess
import sys
import os
import tempfile
import shutil
import time
import ogr
from math import ceil
# from qc_tool.wps.registry import register_check_function

start = time.time()

# NOTE: grass-core and grass-dev package is required

# TODO: move setup_grass_scripting and start_grass functions into helper
def setup_grass_scripting(grass_version):
    """
    setup calling grass functions (for LINUX only!!!)
    :param grass_version: [string]; e.g.: 'grass72'
    :return: path to GISBASE environment variable
    """

    # find GRASS GIS start script path
    startcmd = grass_version + ' --config path'
    try:
        p = subprocess.Popen(startcmd, shell=True,stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate()
    except OSError as error:
        return {"status": "failed",
                "message": "Cannot find GRASS GIS start script {cmd}: {error}".format(cmd=startcmd[0], error=error)}

    # if the error occured, print message and exit
    if p.returncode != 0:
        return {"status": "failed",
                "message": "Issues running GRASS GIS start script"" {cmd}: {error}".format(cmd=' '.join(startcmd),
                                                                                           error=err)}

    # Set GISBASE environment variable
    gisbase = out.strip('\n')
    os.environ['GISBASE'] = gisbase

    # define GRASS-Python environment
    gpydir = os.path.join(gisbase, "etc", "python")
    sys.path.append(gpydir)
    return gisbase

def start_grass(gdbdir, georef_data, version):

    """
    Initialize GRASS GIS session.
    :param georef_data: georeferenced shapefile or georaster
    :param version: [string]: version of GRASS GIS e.g. 'grass'
    :return:
    """

    # create temporary GRASS database directory, location
    GrassDbDir = gdbdir
    location = 'location' # name of location

    # set up grass for scripting...
    gisbase = setup_grass_scripting(version)
    print gisbase

    # Import GRASS Python bindings
    import grass.script as g
    import grass.script.setup as gsetup
    from grass.script import core as grass_core

    # Launch GRASS session
    gsetup.init(gisbase, GrassDbDir)

    # set up CRS using georeferenced data
    grass_core.create_location(GrassDbDir, location, filename=georef_data)

    # launch GRASS session, location, mapset...
    gsetup.init(gisbase, GrassDbDir, location, 'PERMANENT')
    return g

# @register_check_function(__name__, "EPSG code of file CRS match reference EPSG code.")
def run_check(filepath, params):
    """
    CRS check.
    :param filepath: pathname to data source
    :param params: configuration
    :return: status + message
    """


    # convert mmu limit from 'ha' to 'pix' (expected pixel size of 20m)
    mmu_limit = int(ceil(params["area_ha"]*25))

    # TODO: here replace to the temporary dir from params
    clump_centroids = "/home/jiri/Plocha/COP_QC_rasterdata/FTY_2012_020m_eu_03035_d01_E20N10/FTY_2012_020m_eu_03035_d01_E20N10.shp"
    if os.path.isfile(clump_centroids):
        os.remove(clump_centroids)

    # TODO: create GRASS db dir in temporary dir from params
    # start GRASS session
    grass_db_dir = os.path.join(tempfile.gettempdir(), 'grass')  # create GRASS database directory
    if os.path.exists(grass_db_dir):
        shutil.rmtree(grass_db_dir)

    # start GRASS GIS session...
    grass = start_grass(grass_db_dir, filepath, "grass")

    # import source raster data into GRASS environment
    grass.read_command('r.in.gdal', input=filepath, output='inpfile')

    # build clumps with unique codes from source data
    grass.read_command('r.clump', 'd', input='inpfile', output='clumps', title='clumps')

    # create vector layer of centroids of clumps with statistics
    grass.read_command('r.volume', overwrite=True, input='clumps', clump='clumps', centroids='clump_centroids', output='clump_stats')

    # attribute based selection of less-mmu clumps
    grass.read_command('v.extract', input='clump_centroids', output='lessmmu_centroids', where='count < {:s}'.format(str(mmu_limit)))

    # remove redundant fields from attr. table (some attributes contains too large numbers leading to errors in export centroids into shapefile)
    grass.read_command('v.db.dropcolumn', map='lessmmu_centroids', columns='volume, average, sum')

    # export centroids of less-mmu clumps into shapefile
    grass.read_command('v.out.ogr', 'c', input='lessmmu_centroids', output=clump_centroids, format='ESRI_Shapefile',
                       output_layer='clump_centroids')

    # TODO: remove - probably tmp dir will be automatically dropped in dispatch
    # remove temp dir
    shutil.rmtree(grass_db_dir)

    # get lessmmu clumps count
    ds_centr = ogr.Open(clump_centroids)
    lyr_centr = ds_centr.GetLayer()
    lessmmu_count = lyr_centr.GetFeatureCount()
    lyr_centr = None
    ds_centr = None

    if lessmmu_count == 0:
        return {"status": "ok"}
    else:
        return {"status": "failed",
                "message": "The data source has {:s} objects under MMU limit of {:s} ha.".format(str(lessmmu_count),
                                                                                                 str(params["area_ha"]))}


f = "/home/jiri/Plocha/COP_QC_rasterdata/FTY_2012_020m_eu_03035_d01_E20N10/FTY_2012_020m_eu_03035_d01_E20N10.TIF"
par = {"area_ha": 0.5}
print(run_check(f, par))

stop = time.time()
seconds = stop - start
minutes = seconds / 60
hours = minutes / 60
print 'Processing time: %02d:%02d:%02d - %s [s]' % (hours, minutes % 60, seconds % 60, stop - start)
