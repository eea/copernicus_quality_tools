#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Multiparts polygons
"""

from qc_tool.wps.registry import register_check_function

@register_check_function(__name__, "No multipart polygons")
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

    # select all db tables in the current job schema
    job_schema = params["connection_manager"].get_dsn_schema()[1]
    cur.execute("""SELECT table_name FROM information_schema.tables WHERE table_schema='{:s}'""".format(job_schema))
    tables = cur.fetchall()

    valid_tables = [table for table in tables if not ("polyline" in table or "lessmmu" in table or "v6_code" in table)]

    if len(valid_tables) == 0:
        res_message = "The valid codes check failed. The geodatabase does not contain any valid feature class tables."
        return {"status": "failed", "message": res_message}

    res = dict()
    for table in valid_tables:

        # valid_tables wraps the tables inside tuples: unpack tuple here
        table = table[0]
        print("table name: {:s}".format(table))

        # create table of valid code errors
        cur.execute("""SELECT __v8_multipartpolyg('{0}');""".format(table))
        conn.commit()
        multipart_count = cur.fetchone()[0]
        print("multipart_count: {:d}".format(multipart_count))

        if multipart_count == 0:
            return {"status": "ok"}

        # get wrong codes ids and count. the _validcodes_error table was created by the __v6_ValidCodes function.
        cur.execute("""SELECT {0} FROM {1}_multipartpolyg_error""".format(params["ident_colname"], table))
        multipart_error_id_list = [id[0] for id in cur.fetchall()]

        res[table] = {"multipart_error": [multipart_count, ",".join(multipart_error_id_list)]}

        # drop temporary table with code errors
        cur.execute("""DROP TABLE IF EXISTS {:s}_multipartpolyg_error;""".format(table))
        conn.commit()

    lmes = [res[lme]["multipart_error"][0] for lme in res]
    if len(list(set(lmes))) == 0 and lmes[0] == 0:
        return {"status": "ok"}
    else:
        layer_results = ', '.join(
            "layer {!s}: {:d} multipart polygons with wrong code ({!s})".format(key,
                                                                val["multipart_error"][0],
                                                                val["multipart_error"][1]) for (key, val) in res.items()
            if val["multipart_error"][0] != 0)
        res_message = "{:d} multipart polygons found: ({:s}).".format(len(list(set(lmes))), layer_results)
        return {"status": "failed",
                "message": res_message}
