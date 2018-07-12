#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import os
import psycopg2

"""
General methods.
"""


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
