#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import os
import re

from qc_tool.common import FAILED_ITEMS_LIMIT


def dir_recursive_search(in_dir, regexp=".*", target="file", deep=9999, full_path=True):
    results = []
    level = 0
    for root, dirs, files in os.walk(in_dir):
        res = [f for f in os.listdir(root) if re.search(r"{:s}".format(regexp), f)]
        for f in res:
            path = os.path.join(root, f)
            if ((target == "file" and os.path.isfile(path)) or (target == "dir" and os.path.isdir(path))) and (level <= deep):
                if full_path:
                    results.append(path)
                else:
                    results.append(f)
        level += 1
    return results

def do_layers(params):
    return [params["layer_defs"][layer_alias] for layer_alias in params["layers"]]

def shorten_failed_items_message(items, count):
    if len(items) == 0:
        return None
    message = ", ".join(map(str, items))
    if count > len(items):
        message += " and {:d} others".format(count - len(items))
    return message

def get_failed_items_message(cursor, error_table_name, pg_fid_name, limit=FAILED_ITEMS_LIMIT):
    sql = "SELECT {0:s} FROM {1:s} ORDER BY {0:s};".format(pg_fid_name, error_table_name)
    cursor.execute(sql)
    failed_items = [row[0] for row in cursor.fetchmany(limit)]
    failed_items_message = shorten_failed_items_message(failed_items, cursor.rowcount)
    return failed_items_message

def get_failed_pairs_message(cursor, error_table_name, pg_fid_name, limit=FAILED_ITEMS_LIMIT):
    sql = "SELECT a_{0:s}, b_{0:s} FROM {1:s} ORDER BY a_{0:s}, b_{0:s};".format(pg_fid_name, error_table_name)
    cursor.execute(sql)
    failed_pairs = ["{:s}-{:s}".format(str(row[0]), str(row[1])) for row in cursor.fetchmany(limit)]
    failed_pairs_message = shorten_failed_items_message(failed_pairs, cursor.rowcount)
    return failed_pairs_message
