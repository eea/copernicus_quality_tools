#! /usr/bin/env python
# -*- coding: utf-8 -*-

import re
from qc_tool.wps.registry import register_check_function


def check_name(name, template):
    regex = re.compile(template)
    return bool(regex.match(name))


@register_check_function(__name__)
def run_check(params, status):
    # Check file name.
    filename = params["filepath"].name.lower()
    file_regex = params["file_name_regex"].replace("countrycode", params["country_codes"]).lower()
    if not check_name(filename, file_regex):
        status.add_message("File name does not conform to the naming convention.")
        return

    # Check for supplementary files.
    for ext in params["extensions"]:
        other_filepath = params["filepath"].with_suffix(ext)
        if not other_filepath.exists():
            status.add_message("The '{:s}' file is missing.".format(other_filepath.name))

    return
