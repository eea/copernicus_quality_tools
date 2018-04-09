#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""
Import ESRI FGDB into (existing) PostGIS DB.
"""

__author__ = "Jiri Tomicek"
__copyright__ = "Copyright 2018, GISAT s.r.o., CZ"
__email__ = "jiri.tomicek@gisat.cz"
__status__ = "testing"

import commands
import psycopg2
import ogr
import re
import time

file_gdb = '/mnt/gisat_t/orlitova/_COP15m_QC/clc2012_CZ.gdb'

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

def import2pg(db_access, fgdb, fc):
    """
    Import feature class from ESRI FGDB into PostGIS database.
    :param db_access: PostGIS db access information
    :param fgdb: path to file .gdb
    :param fc: feature class name
    :return: True (when import was successful), False (when import failed)
    """

    # import command
    import_cmd = 'ogr2ogr -overwrite -skipfailures ' \
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
                         fc)

    # run import command, return status (+/- response)
    retcode, response = commands.getstatusoutput(import_cmd)
    if retcode != 0:
        print "Error while creating multiband GeoTIFF: %s" % response
        return {"STATUS": "FAILED",
                "MESSAGE": response}
    else:
        return {"STATUS": "OK"}

driver = ogr.GetDriverByName('OpenFileGDB')
o = driver.Open(file_gdb)
for layer in o:
    ln = layer.GetName()
    # print ln

    import2pg(pg_access, file_gdb, ln)


def pg_drop_tables(db_access, re_drop=False):
    """
    Drop all/re-defined tables from PG db.
    :param db_access: PostGIS db access information
    :param re_drop: regex of tables to be dropped
    :return:
    """

    # try to connect to the database
    try:
        conn = psycopg2.connect("dbname='%s' "
                                "user='%s' "
                                "host='%s' "
                                "password='%s'" % (db_access["db_name"],
                                                   db_access["user"],
                                                   db_access["host"],
                                                   db_access["password"]
                                                   ))
    except:
        return {"STATUS": "FAILED",
                "MESSAGE": "UNABLE TO CONNECT TO THE DATABASE"}

    # get list of all tables:
    try:
        cur = conn.cursor()

        # select all user-defined tables (pg_class = catalog of tables (i.a.), relkind='r' = ordinary tables,
        # relname = name of table, relname can not start with pg_ or sql_ substring, rel. spatial_ref_sys contains
        # spatial reference systems definitions)
        cur.execute("""SELECT relname FROM pg_class WHERE relkind='r' AND relname !~ '(^(pg_|sql_)|spatial_ref_sys)';""")
        tables = cur.fetchall()
        conn.commit()
        tables = [table[0] for table in tables]
        # return when database contains no user-defined tables
        if not tables:
            return {"STATUS": "FAILED",
                    "MESSAGE": "DATABASE CONTAINS NO USER-DEFINED TABLES"}
    except:
        return {"STATUS": "FAILED",
                "MESSAGE": "ERROR IN FETCHING DB TABLES"}

    # drop (all/re-specified) tables
    if re_drop:
        regex = re.compile(re_drop)
        tables = filter(lambda i: regex.search(i), tables)

    for table in tables:
        try:
            cur.execute('DROP TABLE "%s"' % table)
            conn.commit()
            print 'DROP TABLE "%s";' % table
            print cur
        except:
            return{"STATUS": "FAILED",
                   "MESSAGE": "FAILED TO DROP TABLE: %s" % table}
    conn.close()
    return {"STATUS": "OK"}

# print pg_drop_tables(pg_access)

stop = time.time()
seconds = stop - start
minutes = seconds/60
hours = minutes/60
print 'Processing time: %02d:%02d:%02d - %s [s]' % (hours, minutes % 60, seconds % 60, stop - start)
