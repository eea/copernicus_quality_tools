#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Valid codes check.
"""

from pathlib import Path, PurePath
#
# from qc_tool.wps.registry import register_check_function
#
# @register_check_function(__name__, "Valid codes check.")
def run_check(filepath, params):
    """
    Minimum mapping unit check..
    :param filepath: pathname to data source
    :param params: configuration
    :return: status + message
    """

    # connection to PG
    conn = params["connection_manager"].get_connection()
    cur = conn.cursor()

    # run command to create custom SQL functions
    # this should be moved to dispatch
    current_directory = PurePath(__file__).parents[0]
    sql_file = PurePath(current_directory, "v6.sql")
    sql_query = Path(sql_file).read_text()
    cur.execute(sql_query)
    conn.commit()

    # select all db tables
    cur.execute("""SELECT relname FROM pg_class WHERE relkind='r' AND relname !~ '(^(pg_|sql_)|spatial_ref_sys)';""")
    tables = cur.fetchall()

    res = dict()
    for table in tables:

        table = table[0]

        if table not in ["clc_code", "ua_code"]:
            continue

        # create table of less-mmu polygons
        cur.execute("""SELECT __V6_ValidCodes('{0}', '{1}');""".format(table, params["product_code"]))
        print(cur.fetchall())
        conn.commit()

        # TODO: zjistis, co vraci funkce __V6_ValidCodes a dopsat

f = ''
p = {"product_code": "clc"}
print(run_check(f, p))
