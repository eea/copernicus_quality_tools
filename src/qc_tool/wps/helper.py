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


def find_name(list_of_names, template):
    """
    Find string from list based on regular expression.
    :param template: regex
    :param list_of_names: list of strings
    :return: list of matching strings
    """
    regex = re.compile(template)
    return filter(regex.match, list_of_names)


def get_substring(name, template):
    """
    Get substring based on regular expression.
    :param name:
    :param template:
    :return: matching substring (or None)
    """
    r = re.compile(template)
    rs = re.search(r, name)
    if rs:
        return str(rs.group(0))
    else:
        return None

def shorten_failed_items_message(items, count):
    if len(items) == 0:
        return None
    message = ", ".join(items)
    if count > len(items):
        message += " and {:d} others".format(count - len(items))
    return message
