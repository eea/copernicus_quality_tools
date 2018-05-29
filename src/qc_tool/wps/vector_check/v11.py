#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Minimum mapping unit check.
"""

from qc_tool.wps.registry import register_check_function
from qc_tool.wps.helper import *


@register_check_function(__name__, "Minimum mapping unit check.")
def run_check(filepath, params):
    """
    Minimum mapping unit check..
    :param filepath: pathname to data source
    :param params: configuration
    :return: status + message
    """

    # query parameters
    border_exception = params["border_exception"]
    area_m = int(params["area_ha"])*10000

    # connection to PG
    conn = params["connection_manager"].get_connection()
    cur = conn.cursor()

    # run command to create custom SQL functions
    # this should be moved to dispatch
    current_directory = os.path.dirname(__file__)
    sql_file = os.path.join(current_directory, "db_functions.sql")
    with open(sql_file, "r") as sql_file_obj:
        sql_query = sql_file_obj.read()
        cur.execute(sql_query)
        conn.commit()


    # select all db tables
    cur.execute("""SELECT relname FROM pg_class WHERE relkind='r' AND relname !~ '(^(pg_|sql_)|spatial_ref_sys)';""")
    tables = cur.fetchall()

    res = dict()
    for table in tables:

        table = table[0]

        # create table of less-mmu polygons
        cur.execute("""SELECT __v11_mmu_status({0},'{1}',{2});""".format(area_m, table, str(border_exception).lower()))
        conn.commit()

        # get less mmu ids and count
        cur.execute("""SELECT id FROM {:s}_lessMMU_error""".format(table))
        lessmmu_error_ids = ', '.join([id[0] for id in cur.fetchall()])
        lessmmu_error_count = cur.rowcount

        if lessmmu_error_count > 0:
            res[table] = {"lessmmu_error": [lessmmu_error_count, lessmmu_error_ids]}
        else:
            res[table] = {"lessmmu_error": [0]}

        if border_exception:
            cur.execute("""SELECT id FROM {:s}_lessMMU_except""".format(table))
            lessmmu_except_ids = ', '.join([id[0] for id in cur.fetchall()])
            lessmmu_except_count = cur.rowcount

            if lessmmu_except_count > 0:
                res[table]["lessmmu_except"] = [lessmmu_except_count, lessmmu_except_ids]
            else:
                res[table]["lessmmu_except"] = [0]

    lmes = [res[lme]["lessmmu_error"][0] for lme in res]
    if len(list(set(lmes))) == 0 and lmes[0] == 0:
        return {"status": "ok"}
    else:
        layer_results = ', '.join(
            "layer {!s}: {:d} polygons under MMU ({!s})".format(key,
                                                                val["lessmmu_error"][0],
                                                                val["lessmmu_error"][1]) for (key, val) in res.items() if val["lessmmu_error"][0] != 0)
        res_message = "The MMU check failed ({:s}).".format(layer_results)
        return {"status": "failed",
                "message": res_message}
