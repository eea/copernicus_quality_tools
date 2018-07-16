#! /usr/bin/env python
# -*- coding: utf-8 -*-

import re
from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    # Check file name.
    filename = params["filepath"].name.lower()
    mobj = re.match(params["file_name_regex"], filename)
    if mobj is None:
        status.add_message("File name does not conform to the naming convention.")
        return

    # Get country code.
    country_code = mobj.group("country_code")
    if country_code not in params["country_codes"]:
        status.aborted()
        status.add_message("File name has illegal country code {:s}.".format(country_code))
        return
    status.add_params({"country_code": country_code})

    # Set reference year.
    status.set_status_property("reference_year", mobj.group("reference_year"))

    # Check for supplementary files.
    for ext in params["extensions"]:
        other_filepath = params["filepath"].with_suffix(ext)
        if not other_filepath.exists():
            status.add_message("The '{:s}' file is missing.".format(other_filepath.name))
