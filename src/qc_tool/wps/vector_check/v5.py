#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Unique identifier check.
"""


from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params):
    """
    Unique identifier check.
    :param params: configuration
    :return: status + message
    """

    # connection to PG
    conn = params["connection_manager"].get_connection()
    cur = conn.cursor()

    res = dict()
    for layer_name in params["layer_names"]:

        # create table of valid code errors
        cur.execute("""SELECT __V5_UniqueID('{0}','{1}');""".format(layer_name, params["product_code"]))
        conn.commit()

        # get wrong UniqueID ids and count. the _uniqueid_error table was created by the __V5_UniqueID function.
        cur.execute("""SELECT {0} FROM {1}_uniqueid_error""".format(params["ident_colname"], layer_name))
        uniqueid_error_ids = ', '.join([id[0] for id in cur.fetchall()])
        uniqueid_error_count = cur.rowcount

        if uniqueid_error_count > 0:
            res[layer_name] = {"uniqueid_error": [uniqueid_error_count, uniqueid_error_ids]}
        else:
            res[layer_name] = {"uniqueid_error": [0]}

        # drop temporary table with code errors
        cur.execute("""DROP TABLE IF EXISTS {:s}_uniqueid_error;""".format(layer_name))
        conn.commit()

        lmes = [res[lme]["uniqueid_error"][0] for lme in res]
        if len(list(set(lmes))) == 0 or lmes[0] == 0:
            return {"status": "ok"}
        else:
            layer_results = ', '.join(
                "layer {!s}: {:d} polygons with wrong code ({!s})".format(key,
                                                                          val["uniqueid_error"][0],
                                                                          val["uniqueid_error"][1]) for (key, val) in
                res.items()
                if val["uniqueid_error"][0] != 0)
            res_message = "The unique identifier check failed ({:s}).".format(layer_results)
            return {"status": "failed",
                    "message": res_message}
