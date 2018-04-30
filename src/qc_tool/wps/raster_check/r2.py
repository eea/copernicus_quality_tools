#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""
Naming convention check.
"""

import os
import re

from qc_tool.wps.registry import register_check_function


__author__ = "Jiri Tomicek"
__copyright__ = "Copyright 2018, GISAT s.r.o., CZ"
__email__ = "jiri.tomicek@gisat.cz"
__status__ = "operational"


@register_check_function(__name__, "File names match file naming conventions.")
def run(filepath, params):
    """
    Check if string matches pattern.
    :param source: name of the file/layer
    :param template: regular_expression
    :return:
    """
    template = params["file_name_regex"]
    regex = re.compile(template)
    filename = os.path.basename(filepath)
    res = bool(regex.match(filename))

    if res:
        return {"status": "ok",
                "message": "Name conforms to the naming convention"}
    else:
        return {"status": "FAILED",
                "message": "Name does not conform to the naming convention"} 
