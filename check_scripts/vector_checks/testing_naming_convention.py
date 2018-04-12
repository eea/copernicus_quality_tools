import re
import ogr
import os
from import_file import import_file

dir_this = os.path.dirname(os.path.realpath(__file__))  # parent directory of this file
par_dir = os.path.abspath(os.path.join(dir_this, os.pardir))
vr2 = import_file(os.path.join(par_dir, 'common_checks/VR2.py'))

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




print vr2.nc_check(source_string_state, template_fc_state)
# print vr2.select_substring(source_string, template_year, pos)

# fgdb = '/home/jtomicek/GISAT/GitHub/copernicus_quality_tools/testing_data/clc2012_mt.gdb'
#
# driver = ogr.GetDriverByName('OpenFileGDB')
# fgdb_open = driver.Open(fgdb)
# for layer in fgdb_open:
#     print layer.GetName()
