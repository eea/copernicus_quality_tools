#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import os
import commands
import psycopg2

"""
General methods.
"""


def dir_recursive_search(in_dir, regexp=".*", target="file", deep=9999, full_path=True):
    results = []
    level = 0
    for root, dirs, files in os.walk(in_dir):
        res = [f for f in os.listdir(root) if re.search(r"{:s}".format(regexp), f)]
        for f in res:
            path = os.path.join(root, f)
            if ((target == "file" and os.path.isfile(path)) or (target == "dir" and os.path.isdir(path))) and (level <= deep):
                if full_path:
                    results.append(path)
                else:
                    results.append(f)
        level += 1
    return results


def check_name(name, template):
    regex = re.compile(template)
    return bool(regex.match(name))


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
                 'PG:"host={0} ' \
                 'user={1} ' \
                 'dbname={2} ' \
                 'password={3}" ' \
                 '{4} ' \
                 '{5}'.format(db_access["host"],
                              db_access["user"],
                              db_access["db_name"],
                              db_access["password"],
                              fgdb,
                              fc)

    # run import command, return status + message
    retcode, response = commands.getstatusoutput(import_cmd)
    if retcode != 0:
        return {"status": "failed",
                "message": response}
    else:
        return {"status": "ok",
                "message": "New table: '{:s}' was created.".format(fc.lower())}

def pg_drop_tables(db_access, re_drop=None):
    """
    Drop all/defined tables from PG db. Define name using regular expression.
    :param db_access: PostGIS db access information
    :param re_drop: regex of tables to be dropped
    :return: Status + message
    """

    # try to connect to the database
    try:
        conn = psycopg2.connect("dbname='{0}' "
                                "user='{1}' "
                                "host='{2}' "
                                "password='{3}'".format(db_access["db_name"],
                                                        db_access["user"],
                                                        db_access["host"],
                                                        db_access["password"]
                                                        ))
    except:
        return {"status": "failed",
                "message": "Unable to connect to the database."}

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
            return {"status": "warning",
                    "message": "Database contains no user-defined tables."}
    except:
        return {"status": "failed",
                "message": "Error in fetching db tables."}

    # drop (all/specified) tables
    if re_drop:
        regex = re.compile(re_drop)
        tables = filter(lambda i: regex.search(i), tables)
        if not tables:
            return{"status": "warning",
                   "message": "Database contains no specified tables matching with regexp='{:s}'.".format(re_drop)}

    for table in tables:
        try:
            cur.execute('DROP TABLE "{:s}"'.format(table))
            conn.commit()
        except:
            return{"status": "failed",
                   "message": "Failed to drop table: {:s}.".format(table)}
    conn.close()
    return {"status": "ok",
            "message": "{:d} tables were dropped.".format(len(tables))}

