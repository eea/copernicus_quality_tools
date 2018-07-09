#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Multiparts polygons
"""


from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params):
    """
    Minimum mapping unit check..
    :param params: configuration
    :return: status + message
    """

    # connection to PG
    conn = params["connection_manager"].get_connection()
    cur = conn.cursor()

    res = dict()
    for layer_name in params["layer_names"]:

        # create table of valid code errors
        cur.execute("""SELECT __v8_multipartpolyg('{0}');""".format(layer_name))
        conn.commit()
        multipart_count = cur.fetchone()[0]
        print("multipart_count: {:d}".format(multipart_count))

        if multipart_count == 0:
            return {"status": "ok"}

        # get wrong codes ids and count. the _validcodes_error table was created by the __v6_ValidCodes function.
        cur.execute("""SELECT {0} FROM {1}_multipartpolyg_error""".format(params["ident_colname"], layer_name))
        multipart_error_id_list = [id[0] for id in cur.fetchall()]

        res[layer_name] = {"multipart_error": [multipart_count, ",".join(multipart_error_id_list)]}

        # drop temporary table with code errors
        cur.execute("""DROP TABLE IF EXISTS {:s}_multipartpolyg_error;""".format(layer_name))
        conn.commit()

    lmes = [res[lme]["multipart_error"][0] for lme in res]
    if len(list(set(lmes))) == 1 and lmes[0] == 0:
        return {"status": "ok"}
    else:
        layer_results = ', '.join(
            "layer {!s}: {:d} multipart polygons with wrong code ({!s})".format(key,
                                                                val["multipart_error"][0],
                                                                val["multipart_error"][1]) for (key, val) in res.items()
            if val["multipart_error"][0] != 0)
        res_message = "{:d} multipart polygons found: ({:s}).".format(len(list(set(lmes))), layer_results)
        return {"status": "failed",
                "messages": [res_message]}
