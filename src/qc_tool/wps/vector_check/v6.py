#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Valid codes check.
"""


from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params):
    """
    Valid codes check.
    :param params: configuration
    :return: status + message
    """

    # connection to PG
    conn = params["connection_manager"].get_connection()
    cur = conn.cursor()

    res = dict()
    for layer_name in params["layer_names"]:

        # create table of valid code errors
        cur.execute("""SELECT __V6_ValidCodes('{0}', '{1}');""".format(layer_name, params["product_code"]))
        conn.commit()

        # get wrong codes ids and count. the _validcodes_error table was created by the __v6_ValidCodes function.
        cur.execute("""SELECT {0} FROM {1}_validcodes_error""".format(params["ident_colname"], layer_name))
        validcodes_error_ids = ', '.join([id[0] for id in cur.fetchall()])
        validcodes_error_count = cur.rowcount

        if validcodes_error_count > 0:
            res[layer_name] = {"validcodes_error": [validcodes_error_count, validcodes_error_ids]}
        else:
            res[layer_name] = {"validcodes_error": [0]}

        # drop temporary table with code errors
        cur.execute("""DROP TABLE IF EXISTS {:s}_validcodes_error;""".format(layer_name))
        conn.commit()

    lmes = [res[lme]["validcodes_error"][0] for lme in res]
    if len(list(set(lmes))) == 1 and lmes[0] == 0:
        return {"status": "ok"}
    else:
        layer_results = ', '.join(
            "layer {!s}: {:d} polygons with wrong code ({!s})".format(key,
                                                                val["validcodes_error"][0],
                                                                val["validcodes_error"][1]) for (key, val) in res.items()
            if val["validcodes_error"][0] != 0)
        res_message = "The valid codes check failed ({:s}).".format(layer_results)
        return {"status": "failed",
                "messages": [res_message]}
