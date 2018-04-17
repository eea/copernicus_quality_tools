#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""
Naming convention check.
"""

import re

__author__ = "Jiri Tomicek"
__copyright__ = "Copyright 2018, GISAT s.r.o., CZ"
__email__ = "jiri.tomicek@gisat.cz"
__status__ = "operational"


def run_check(source, template):
    """
    Check if string matches pattern.
    :param source: name of the file/layer
    :param template: regular_expression
    :return: status + message
    """
    source = source.lower()
    regex = re.compile(template)
    res = bool(regex.match(source))

    if res:
        return {"STATUS": "OK",
                "MESSAGE": "NAME CONFORMS TO THE NAMING CONVENTION"}
    else:
        return {"STATUS": "FAILED",
                "MESSAGE": "NAME DOES NOT CONFORM TO THE NAMING CONVENTION"}


def select_substring(source, template, position=False):
    """
    Select substring matching regexp pattern.
    :param source: source string
    :param template: regexp template
    :param position: [optional] position in the substring
    :return: Substring (if pattern occurs in source) or False
    """
    source = str(source).lower()
    res = re.search(template, source)
    if res:
        return res.group(1)[position[0]: position[1]]
    else:
        return False
