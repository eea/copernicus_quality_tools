#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""
Naming convention check.
"""

import os
import re

from qc_tool.wps.registry import register_check_function
from qc_tool.wps.helper import *

@register_check_function(__name__, "File names match file naming conventions.")
def run_check(filepath, params):
    """
    Check if string matches pattern.
    :param filepath: pathname to data source
    :param params: configuration
    :return: status + message
    """

    # check file name
    filename = os.path.basename(filepath).lower()
    file_regex = params["file_name_regex"].replace("countrycode", params["country_codes"]).lower()
    if not check_name(filename, file_regex):
        print("failed")
        return {"status": "failed",
                "message": "File name does not conform to the naming convention."}
    else:
        list_of_files = [x.lower() for x in os.listdir(os.path.dirname(filepath))]
        file_prefix = os.path.splitext(filename)[0]

        # check for required files
        for ext in params["extensions"]:
            req_file = file_prefix + ext
            if req_file not in list_of_files:
                return {"status": "failed",
                        "message": "'{:s}' file is missing.".format(ext)}
        return {"status": "ok",
                "message": "The file naming convention check was successfull."}
