#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""
Import ESRI FGDB into (existing) PostGIS DB.
"""

import commands
import psycopg2
import re

__author__ = "Jiri Tomicek"
__copyright__ = "Copyright 2018, GISAT s.r.o., CZ"
__email__ = "jiri.tomicek@gisat.cz"
__status__ = "operational"


def import2pg(db_access, fgdb, fc):
    """
    Import feature class from ESRI FGDB into PostGIS database.
    :param db_access: PostGIS db access information
    :param fgdb: path to file .gdb
    :param fc: feature class name
    :return: Status + message
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

    # run import command, return status + message
    retcode, response = commands.getstatusoutput(import_cmd)
    if retcode != 0:
        return {"STATUS": "FAILED",
                "MESSAGE": response}
    else:
        return {"STATUS": "OK",
                "MESSAGE": "NEW TABLE: '%s' WAS CREATED" % fc.lower()}


def pg_drop_tables(db_access, re_drop=False):
    """
    Drop all/defined tables from PG db. Define name using regular expression.
    :param db_access: PostGIS db access information
    :param re_drop: regex of tables to be dropped
    :return: Status + message
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
        # relname = name of table, relname can not start with pg_ or sql_ substring, table spatial_ref_sys contains
        # spatial reference systems definitions)
        cur.execute("""SELECT relname FROM pg_class WHERE relkind='r' AND relname !~ '(^(pg_|sql_)|spatial_ref_sys)';""")
        tables = cur.fetchall()
        conn.commit()
        tables = [table[0] for table in tables]

        # return when database contains no user-defined tables
        if not tables:
            return {"STATUS": "WARNING",
                    "MESSAGE": "DATABASE CONTAINS NO USER-DEFINED TABLES"}
    except:
        return {"STATUS": "FAILED",
                "MESSAGE": "ERROR IN FETCHING DB TABLES"}

    # drop (all/specified) tables
    if re_drop:
        regex = re.compile(re_drop)
        tables = filter(lambda i: regex.search(i), tables)
        if not tables:
            return{"STATUS": "WARNING",
                   "MESSAGE": "DATABASE CONTAINS NO SPECIFIED TABLES MATCHING WITH REGEXP='%s'" % re_drop}

    for table in tables:
        try:
            cur.execute('DROP TABLE "%s"' % table)
            conn.commit()
        except:
            return{"STATUS": "FAILED",
                   "MESSAGE": "FAILED TO DROP TABLE: %s" % table}
    conn.close()
    return {"STATUS": "OK",
            "MESSAGE": "%d TABLES WERE DROPPED" % len(tables)}
