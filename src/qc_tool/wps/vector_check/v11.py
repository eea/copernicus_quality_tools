#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Minimum mapping unit check.
"""


from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    """
    Minimum mapping unit check..
    :param params: configuration
    :return: status + message
    """

    # query parameters
    border_exception = params["border_exception"]
    area_m = int(params["area_ha"])*10000

    # connection to PG
    conn = params["connection_manager"].get_connection()
    cur = conn.cursor()

    res = dict()
    for layer_name in params["layer_names"]:

        # Calling a custom postgres function to create table of less-mmu polygons
        cur.execute("""SELECT __v11_mmu_status({0},'{1}',{2});""".format(area_m, layer_name, str(border_exception).lower()))
        conn.commit()

        # get less mmu ids and count. the _lessmmu_error table was created by the __v11_mmu_status function.
        cur.execute("""SELECT {0} FROM {1}_lessmmu_error""".format(params["ident_colname"], layer_name))
        lessmmu_error_ids = ', '.join([id[0] for id in cur.fetchall()])
        lessmmu_error_count = cur.rowcount

        if lessmmu_error_count > 0:
            res[layer_name] = {"lessmmu_error": [lessmmu_error_count, lessmmu_error_ids]}
        else:
            res[layer_name] = {"lessmmu_error": [0]}

        # drop temporary table with code errors
        cur.execute("""DROP TABLE IF EXISTS {:s}_lessmmu_error;""".format(layer_name))
        conn.commit()

        if border_exception:
            cur.execute("""SELECT {0} FROM {1}_lessmmu_except""".format(params["ident_colname"], layer_name))
            lessmmu_except_ids = ', '.join([id[0] for id in cur.fetchall()])
            lessmmu_except_count = cur.rowcount

            if lessmmu_except_count > 0:
                res[layer_name]["lessmmu_except"] = [lessmmu_except_count, lessmmu_except_ids]
            else:
                res[layer_name]["lessmmu_except"] = [0]

            # drop temporary table with code errors
            cur.execute("""DROP TABLE IF EXISTS {:s}_lessmmu_except;""".format(layer_name))
            conn.commit()

    lmes = [res[lme]["lessmmu_error"][0] for lme in res]
    if len(list(set(lmes))) == 1 and lmes[0] == 0:
        return
    else:
        layer_results = ', '.join(
            "layer {!s}: {:d} polygons under MMU ({!s})".format(key,
                                                                val["lessmmu_error"][0],
                                                                val["lessmmu_error"][1]) for (key, val) in res.items() if val["lessmmu_error"][0] != 0)
        res_message = "The MMU check failed ({:s}).".format(layer_results)
        status.add_message(res_message)
        return
