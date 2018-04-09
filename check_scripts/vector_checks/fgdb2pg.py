#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""
Import ESRI FGDB into (existing) PostGIS DB.
"""

__author__ = "Jiri Tomicek"
__copyright__ = "Copyright 2018, GISAT s.r.o., CZ"
__email__ = "jiri.tomicek@gisat.cz"
__status__ = "testing"

import ogr
import os

fgdb = '/home/jtomicek/GISAT/GitHub/copernicus_quality_tools/testing_data/clc2012_mt.gdb'
pg_access = {
    "db_name": "cop",
    "host": "192.168.2.72",
    "user": "jiri",
    "password": ""
}


driver = ogr.GetDriverByName("OpenFileGDB")

fgdb_open = driver.Open(fgdb)

for layer in fgdb_open:
    layer_name = layer.GetName()
    print layer_name

def import2pg(layer, db_access):
    """
    Import ogr layer into PostGIS database
    :param layer: ogr layer
    :param db_access: access db informations
    :return:
    """

    conn_str = "PG: host=%s dbname=%s user=%s password=%s" % (db_access["host"],
                                                              db_access["db_name"],
                                                              db_access["user"],
                                                              db_access["password"])
    print conn_str
    conn = ogr.Open(conn_str)
    print 'conn', conn

    import_str = 'ogr2ogr -overwrite -skipfailures ' \
                 '-f "PostgreSQL" ' \
                 'PG:"host=%s ' \
                 'user=%s ' \
                 'dbname=%s ' \
                 'password=%s" ' \
                 '%s ' \
                 '%s' % (db_access["host"],
                         db_access["user"],
                         db_access["db_name"],
                         db_access["password"],
                         fgdb,
                         layer)
    os.system(import_str)



import2pg(layer_name, pg_access)











def format_pg(db_access):
    """
    Drop all tables from PostGIS database.
    :param db_access:
    :return:
    """

    # # test: get layer from postgis db
    # connString = "PG: host=%s dbname=%s user=%s password=%s" % (db_access["host"],
    #                                                             db_access["db_name"],
    #                                                             db_access["user"],
    #                                                             db_access["password"])
    # conn = ogr.Open(connString)
    # for i in conn:
    #     daLayer = i.GetName()
    #     print daLayer