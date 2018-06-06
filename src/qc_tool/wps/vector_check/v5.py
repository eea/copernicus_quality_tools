#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Valid codes check.
"""

from qc_tool.wps.registry import register_check_function

@register_check_function(__name__, "Unique identifier check.")
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
        res_message = "The unique identifier check failed. The geodatabase does not contain any valid feature class tables."
        return {"status": "failed", "message": res_message}

    res = dict()
    for table in valid_tables:

        table = table[0]

        # create table of valid code errors
        cur.execute("""SELECT __v5_uniqueid('{0}', '{1}');""".format(table, params["product_code"]))
        conn.commit()

        non_unique_ids = [id[0] for id in cur.fetchall()]
        if len(non_unique_ids) > 0 and non_unique_ids[0] == 0:
            return {"status": "ok"}
        else:
            res_message = "non-unique ID values found: " + ",".join(non_unique_ids)
            return {"status": "failed",
                    "message": res_message}
