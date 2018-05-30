#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""
Naming convention check.
"""

from pathlib import Path, PurePath

from qc_tool.wps.registry import register_check_function
from qc_tool.wps.helper import check_name

@register_check_function(__name__, "File names match file naming conventions.")
def run_check(filepath, params):
    """
    Check if string matches pattern.
    :param filepath: pathname to data source
    :param params: configuration
    :return: status + message
    """

    # check file name
    filename = PurePath(filepath).name
    filename = filename.lower()
    file_regex = params["file_name_regex"].replace("countrycode", params["country_codes"]).lower()
    if not check_name(filename, file_regex):
        return {"status": "failed",
                "message": "File name does not conform to the naming convention."}
    else:
        list_of_files = [str(x).lower() for x in Path(PurePath(filepath).parents[0]).iterdir()]
        file_stem = PurePath(filename).stem

        # check for required files
        for ext in params["extensions"]:
            req_file = file_stem + ext
            if req_file not in list_of_files:
                return {"status": "failed",
                        "message": "The '{:s}' file is missing.".format(req_file)}
        return {"status": "ok"}
