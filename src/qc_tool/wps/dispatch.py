#!/usr/bin/env python3


import json
from os.path import normpath
from pathlib import Path

from registry import get_check_function

import common_check.vr1



# FIXME: such normalization should be removed in python3.6.
QC_TOOL_HOME = Path(__file__).joinpath("../../..")
PRODUCT_TYPES_DIR = QC_TOOL_HOME.joinpath("product_types")
CHECK_DEFAULTS_FILENAME = "_check_defaults.json"


def read_product_types(product_type_dir):
    """Returns list of product type names.

    Product type names are all items in directory product_type_configs whose names start with alnum character.
    So for example filenames starting with "_", "." are excluded."""
    raise TodoException()

def dispatch(filepath, product_type_name, optional_check_idents):
    # Read configurations.
    check_defaults_filepath = PRODUCT_TYPES_DIR.joinpath(CHECK_DEFAULTS_FILENAME)
    check_defaults = json.loads(common_config_filepath.read_text())
    product_type_filepath = PRODUCT_TYPES_DIR.joinpath("{:s}.json".format(product_type_name))
    product_type = json.loads(product_type_filepath.read_text())

    # Prepare check idents.
    product_check_idents = set(check["check_ident"] for check in product_type["checks"])
    optional_check_idents = set(optional_check_idents)

    # Ensure passed optional checks take part in product type.
    incorrect_check_idents = optional_check_idents - product_check_idents
    if len(incorrect_check_idents) > 0:
        raise ServiceException("Incorrect checks passed, product_type_name={:s}, incorrect_check_idents={:s}.".format(repr(product_type_name), repr(sorted(incorrect_check_idents))))

    # Compile check suite to be performed.
    check_suite = [check
                   for check in product_type["checks"]
                   if check["required"] or check["check_ident"] in optional_check_idents]

    # Run check suite.
    suite_result = {}
    for check in check_suite:
        # Prepare parameteres.
        params = {}
        if "parameters" in product_type:
            params.update(product_type["parameters"])
        if check["check_ident"] in check_defaults:
            params.update(check_defaults[check["check_ident"]])
        if "parameters" in check:
            params.update(check["parameters"])

        # Run the check.
        func = get_check_function(check["check_ident"])
        check_result = func(filepath, params)
        if "fatal_error" in check_result:
            suite_result.update(check_result)
            return suite_result
        else:
            suite_result[check["check_ident"]] = check_result
    return suite_result


class ServiceException(Exception):
    pass
