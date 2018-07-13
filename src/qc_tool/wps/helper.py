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


def check_name(name, template):
    regex = re.compile(template)
    return bool(regex.match(name))

def shorten_failed_items_message(items, count):
    if len(items) == 0:
        return None
    message = ", ".join(items)
    if count > len(items):
        message += " and {:d} others".format(count - len(items))
    return message

def get_failed_ids_message(cursor, error_table_name, ident_colname, limit=FAILED_ITEMS_LIMIT):
    sql = "SELECT {0:s} FROM {1:s} ORDER BY {0:s};".format(ident_colname, error_table_name)
    cursor.execute(sql)
    failed_ids = [row[0] for row in cursor.fetchmany(limit)]
    failed_ids_message = shorten_failed_items_message(failed_ids, cursor.rowcount)
    return failed_ids_message
