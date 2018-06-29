#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Neighbouring polygons code check.
"""


from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params):
    """
    Neighbouring polygons with the same code.
    :param params: configuration
    :return: status + message
    """

    # connection to PG
    conn = params["connection_manager"].get_connection()
    cur = conn.cursor()

    # select all db tables in the current job schema
    job_schema = params["connection_manager"].get_dsn_schema()[1]
    cur.execute("""SELECT table_name FROM information_schema.tables WHERE table_schema='{:s}'""".format(job_schema))
    tables = cur.fetchall()

    valid_tables = [table for table in tables if not ("polyline" in table or "v6_code" in table)]

    if len(valid_tables) == 0:
        res_message = "The valid codes check failed. The geodatabase does not contain any valid feature class tables."
        return {"status": "failed", "message": res_message}

    res = dict()
    for table in valid_tables:
        table = table[0]

        # create table of valid code errors
        cur.execute("""SELECT __V14_NeighbCodes('{0}', '{1}');""".format(table, params["product_code"]))
        conn.commit()

        # get wrong codes ids and count. the _neighbcode_error table was created by the __V14_NeighbCodes function.
        cur.execute("""SELECT {0} FROM {1}_neighbcode_error""".format(params["ident_colname"], table))
        neighbcode_error_ids = ', '.join([id[0] for id in cur.fetchall()])
        neighbcode_error_count = cur.rowcount

        if neighbcode_error_count > 0:
            res[table] = {"neighbcode_error": [neighbcode_error_count, neighbcode_error_ids]}
        else:
            res[table] = {"neighbcode_error": [0]}

        # drop temporary table with code errors
        cur.execute("""DROP TABLE IF EXISTS {:s}_neighbcode_error;""".format(table))
        conn.commit()

        lmes = [res[lme]["neighbcode_error"][0] for lme in res]
        if len(list(set(lmes))) == 0 or lmes[0] == 0:
            return {"status": "ok"}

        else:
            layer_results = ', '.join(
                "layer {!s}: {:d} polygons has the same code as their neighbour ({!s})".format(key,
                                                                          val["neighbcode_error"][0],
                                                                          val["neighbcode_error"][1]) for (key, val) in
                res.items()
                if val["neighbcode_error"][0] != 0)
            res_message = "The neighbouring polygons code check. ({:s}).".format(layer_results)
            return {"status": "failed",
                    "message": res_message}
