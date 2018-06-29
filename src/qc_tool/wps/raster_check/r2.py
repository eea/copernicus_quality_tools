#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""
Naming convention check.
"""


from qc_tool.wps.helper import check_name
from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params):
    """
    Check if string matches pattern.
    :param params: configuration
    :return: status + message
    """
    # Check file name.
    filename = params["filepath"].name.lower()
    file_regex = params["file_name_regex"].replace("countrycode", params["country_codes"]).lower()
    if not check_name(filename, file_regex):
        return {"status": "failed",
                "message": "File name does not conform to the naming convention."}

    # Check for supplementary files.
    for ext in params["extensions"]:
        other_filepath = params["filepath"].with_suffix(ext)
        if not other_filepath.exists():
            return {"status": "failed",
                        "message": "The '{:s}' file is missing.".format(other_filepath.name)}

    return {"status": "ok"}
