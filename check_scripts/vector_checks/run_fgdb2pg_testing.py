import time
import ogr
from import_file import import_file
import os

file_gdb = '/mnt/gisat_t/orlitova/_COP15m_QC/UA/ES014L2_PAMPLONA_IRUNA.gdb'

dir_this = os.path.dirname(os.path.realpath(__file__))  # parent directory of this file

fgdb2pg = import_file(os.path.join(dir_this, 'fgdb2pg.py'))


# db Erika
# pg_access = {
#     "db_name": "cop_erika",
#     "host": "192.168.2.72",
#     "user": "jiri",
#     "password": ""
# }

# db moje
pg_access = {
    "db_name": "cop",
    "host": "192.168.2.72",
    "user": "jiri",
    "password": ""
}

start = time.time()

# import to PG
driver = ogr.GetDriverByName('OpenFileGDB')
o = driver.Open(file_gdb)
# ln = o.GetLayerByName('ES014L2_PAMPLONA_IRUNA_UA2006_2012')
# for layer in o:
#     ln = layer.GetName()
#     print ln
# print fgdb2pg.import2pg(pg_access, file_gdb, 'ES014L2_PAMPLONA_IRUNA_UA2006_2012')


# drop table from PG
print fgdb2pg.pg_drop_tables(pg_access, re_drop='diss$')



stop = time.time()
seconds = stop - start
minutes = seconds/60
hours = minutes/60
print 'Processing time: %02d:%02d:%02d - %s [s]' % (hours, minutes % 60, seconds % 60, stop - start)