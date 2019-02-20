#! /usr/bin/env python
# -*- coding: utf-8 -*-


import re


def run_check(params, status):
    # Check file name.
    filename = params["filepath"].name.lower()
    mobj = re.match(params["file_name_regex"], filename)
    if mobj is None:
        status.aborted("File name does not conform to the naming convention.")
        return

    # Get country code.
    country_code = mobj.group("country_code")
    if country_code not in params["country_codes"]:
        status.aborted("File name has illegal country code {:s}.".format(country_code))
        return
    status.add_params({"country_code": country_code})

    # Set reference year.
    status.set_status_property("reference_year", mobj.group("reference_year"))

    # Check for supplementary files.

    # The extension can be specified as .clr or .tif.clr (.clr|.tif.clr)
    for ext in params["extensions"]:
        if "|" in ext:
            ext_options = ext.split("|")
        else:
            ext_options = [ext]

        expected_supplementary_files = [params["filepath"].with_suffix(ext_opt).name for ext_opt in ext_options]

        found_files = []
        if len(expected_supplementary_files) == 1:
            expected_files_msg = expected_supplementary_files[0]
        else:
            expected_files_msg = " or ".join(expected_supplementary_files)

        for ext2 in ext_options:
            other_filepath = params["filepath"].with_suffix(ext2)
            if other_filepath.exists():
                found_files.append(other_filepath.name)

        if len(found_files) == 0:
            status.aborted("The expected  file '{:s}' is missing.".format(expected_files_msg))
            return
