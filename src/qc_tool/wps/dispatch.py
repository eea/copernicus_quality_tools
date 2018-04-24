#!/usr/bin/env python3

import json
from os.path import normpath
from pathlib import Path

from registry import get_check_function

import common_check.vr1

# FIXME: such normalization should be removed in python3.6.
PRODUCT_CONFIG_DIR = Path(normpath(str(Path(__file__, "..", "product_types"))))
COMMON_CONFIG_NAME = "_common.json"

# FIXME: this function should be removed in favour of path.read_text().
def read_file(filepath):
    with open(str(filepath), "rt", encoding="UTF-8") as f:
        text = f.read()
    return text

def read_product_types(product_type_dir):
    """Returns list of product type names.

    Product type names are all items in directory product_type_configs whose names start with alnum character.
    So for example filenames starting with "_", "." are excluded."""
    raise TodoException()

def dispatch(filepath, product_type_name, optional_check_idents):
    # Read configurations.
    common_config_filepath = PRODUCT_CONFIG_DIR.joinpath(COMMON_CONFIG_NAME)
    common_config = json.loads(read_file(common_config_filepath))
    product_config_filepath = PRODUCT_CONFIG_DIR.joinpath("{:s}.json".format(product_type_name))
    product_config = json.loads(read_file(product_config_filepath))

    # Prepare check idents.
    product_check_idents = set(check["check_ident"] for check in product_config["checks"])
    optional_check_idents = set(optional_check_idents)

    # Ensure passed optional checks take part in product type.
    incorrect_check_idents = optional_check_idents - product_check_idents
    if len(incorrect_check_idents) > 0:
        raise ServiceException("Incorrect checks passed, product_type_name={:s}, incorrect_check_idents={:s}.".format(repr(product_type_name), repr(sorted(incorrect_check_idents))))

    # Compile suit of checks to be performed.
    check_idents = product_check_idents | optional_check_idents
    check_suite = [check for check in product_config["checks"] if check["check_ident"] in check_idents]

    # Run check suite.
    suite_result = {}
    for check in check_suite:
        check_ident = check["check_ident"]
        func = get_check_function(check_ident)
        params = {}
        params.update(common_config)
        params.update(product_config["parameters"])
        params.update(check["parameters"])
        check_result = func(filepath, params)
        if "fatal_error" in check_result:
            suite_result.update(check_result)
            return suite_result
        else:
            suite_result[check_ident] = check_result
    return suite_result


class ServiceException(Exception):
    pass
