import re
import ogr
import os
from import_file import import_file


input_file_gdb = "/home/jtomicek/GISAT/GitHub/copernicus_quality_tools/testing_data/clc2012_mt.gdb"
input_file_shp = "/home/jtomicek/Desktop/Subdivide2017/lpis2017.shp"
input_file_geojson = "/mnt/freenas_pracovni_archiv_01/Sentinel-2/MSI/2016/S2A/S2MSI2I/33UVR/S2A_USER_PRD_MSIL2I_PDMC_20160418T124555_R022_V20160409T101141_20160409T101141.geojson"
input_file_tif = "/home/jtomicek/Desktop/NRERI_outputs/20170928T100021_NRERI.tif"
input_from_config = {"check_id": "V1", "check_name": "file format", "parameters": [{"name": "format", "value": [".gdb", ".tif", ".geojson"], "exceptions": []}]}
# fj = "/home/jtomicek/GISAT/GitHub/copernicus_quality_tools/check_scripts/common_checks/config_files/gdal_ogr_drivers.json"


dir_this = os.path.dirname(os.path.realpath(__file__))  # parent directory of this file
ogr_gdal_drivers = os.path.join(dir_this, 'config_files', 'general', "gdal_ogr_drivers.json")
vr2 = import_file(os.path.join(dir_this, 'common_checks', 'VR2.py'))
vr1 = import_file(os.path.join(dir_this, 'common_checks', 'VR1.py'))

# source_string = "clca2012_cz.gdb"
# source_string = "cz"
# source_string = "clca2012_cz.gdb"

# source_string = "ahojFF2018fdaFF228fs"
# source_string_change = 'cha12_MT'
source_string_state = 'clc06_MT'

pos = [-2, None]

# TEMPLATES FOR CLC CHECKS
# template_gdb = "^clc(\d\d\d\d)_[a-z][a-z]\.gdb$"
# template_fd = "^[a-z][a-z]$"
# template_fc_change = "^cha(\d\d)_[a-z][a-z]$"
template_fc_state = "^clc(\d\d)_[a-z][a-z]$"
# template_year = "(\d\d\d\d)"




# print vr2.nc_check(source_string_state, template_fc_state)
# print vr2.select_substring(source_string, template_year, pos)

# fgdb = '/home/jtomicek/GISAT/GitHub/copernicus_quality_tools/testing_data/clc2012_mt.gdb'
#
# driver = ogr.GetDriverByName('OpenFileGDB')
# fgdb_open = driver.Open(fgdb)
# for layer in fgdb_open:
#     print layer.GetName()

status, message = vr1.run_check(input_from_config, input_file_tif, ogr_gdal_drivers).values()

print "%s: %s" % (status, message)

