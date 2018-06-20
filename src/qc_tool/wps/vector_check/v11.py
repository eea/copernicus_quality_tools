#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Minimum mapping unit check.
"""


from qc_tool.wps.registry import register_check_function

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

    # select all db tables in the current job schema
    job_schema = params["connection_manager"].get_dsn_schema()[1]
    cur.execute("""SELECT table_name FROM information_schema.tables WHERE table_schema='{:s}'""".format(job_schema))
    tables = cur.fetchall()

    valid_tables = [table for table in tables if not ("polyline" in table or "lessmmu" in table or "v6_code" in table)]

    if len(valid_tables) == 0:
        res_message = "The MMU check failed. The geodatabase does not contain any valid feature class tables."
        return {"status": "failed", "message": res_message}

    res = dict()
    for table in valid_tables:

        table = table[0]

        # Calling a custom postgres function to create table of less-mmu polygons
        cur.execute("""SELECT __v11_mmu_status({0},'{1}',{2});""".format(area_m, table, str(border_exception).lower()))
        conn.commit()

        # get less mmu ids and count. the _lessmmu_error table was created by the __v11_mmu_status function.
        cur.execute("""SELECT {0} FROM {1}_lessmmu_error""".format(params["ident_colname"], table))
        lessmmu_error_ids = ', '.join([id[0] for id in cur.fetchall()])
        lessmmu_error_count = cur.rowcount

        if lessmmu_error_count > 0:
            res[table] = {"lessmmu_error": [lessmmu_error_count, lessmmu_error_ids]}
        else:
            res[table] = {"lessmmu_error": [0]}

        # drop temporary table with code errors
        cur.execute("""DROP TABLE IF EXISTS {:s}_lessmmu_error;""".format(table))
        conn.commit()

        if border_exception:
            cur.execute("""SELECT {0} FROM {1}_lessmmu_except""".format(params["ident_colname"], table))
            lessmmu_except_ids = ', '.join([id[0] for id in cur.fetchall()])
            lessmmu_except_count = cur.rowcount

            if lessmmu_except_count > 0:
                res[table]["lessmmu_except"] = [lessmmu_except_count, lessmmu_except_ids]
            else:
                res[table]["lessmmu_except"] = [0]

            # drop temporary table with code errors
            cur.execute("""DROP TABLE IF EXISTS {:s}_lessmmu_except;""".format(table))
            conn.commit()

    lmes = [res[lme]["lessmmu_error"][0] for lme in res]
    if len(list(set(lmes))) == 0 or lmes[0] == 0:
        return {"status": "ok"}
    else:
        layer_results = ', '.join(
            "layer {!s}: {:d} polygons under MMU ({!s})".format(key,
                                                                val["lessmmu_error"][0],
                                                                val["lessmmu_error"][1]) for (key, val) in res.items() if val["lessmmu_error"][0] != 0)
        res_message = "The MMU check failed ({:s}).".format(layer_results)
        return {"status": "failed",
                "message": res_message}
