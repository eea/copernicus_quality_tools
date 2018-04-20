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


def nc_check(source, template):
    """
    Check if string matches pattern.
    :param source: name of the file/layer
    :param template: regular_expression
    :return:
    """
    regex = re.compile(template)
    res = bool(regex.match(source))

    if res:
        return {"STATUS": "OK",
                "MESSAGE": "NAME CONFORMS TO THE NAMING CONVENTION"}
    else:
        return {"STATUS": "FAILED",
                "MESSAGE": "NAME DOES NOT CONFORM TO THE NAMING CONVENTION"}
