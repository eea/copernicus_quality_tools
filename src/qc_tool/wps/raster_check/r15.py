#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Check colors in the color table
"""

import ogr

from qc_tool.wps.registry import register_check_function

@register_check_function(__name__, "Colors in the color table match product specification")
def run_check(filepath, params):
    """
    :param colors: a dictionary of raster values and associated [r,g,b] colors
    :return: status + message
    """
    return {"status": "failed",
            "message": "The r15 check is not implemented yet."}
