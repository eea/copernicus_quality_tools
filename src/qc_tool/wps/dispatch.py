#!/usr/bin/env python3


import json
from os.path import normpath
from pathlib import Path

from qc_tool.wps.registry import get_check_function

import qc_tool.wps.common_check.dummy
import qc_tool.wps.common_check.vr1

import qc_tool.wps.raster_check.r1
import qc_tool.wps.raster_check.r4
import qc_tool.wps.vector_check.v1
import qc_tool.wps.vector_check.v4



# FIXME: such normalization should be removed in python3.6.
QC_TOOL_HOME = Path(normpath(str(Path(__file__).joinpath("../../../.."))))
PRODUCT_TYPES_DIR = QC_TOOL_HOME.joinpath("product_types")
CHECK_DEFAULTS_FILENAME = "_check_defaults.json"


def read_product_types(product_type_dir):
    """Returns list of product type names.

    Product type names are all items in directory product_type_configs whose names start with alnum character.
    So for example filenames starting with "_", "." are excluded."""
    raise TodoException()

def dispatch(filepath, product_type_name, optional_check_idents, params=None, update_result=None):
    # Read configurations.
    check_defaults_filepath = PRODUCT_TYPES_DIR.joinpath(CHECK_DEFAULTS_FILENAME)
    check_defaults = json.loads(check_defaults_filepath.read_text())
    product_type_filepath = PRODUCT_TYPES_DIR.joinpath("{:s}.json".format(product_type_name))
    product_type = json.loads(product_type_filepath.read_text())

    # Prepare check idents.
    product_check_idents = set(check["check_ident"] for check in product_type["checks"])
    optional_check_idents = set(optional_check_idents)

    # Ensure passed optional checks take part in product type.
    incorrect_check_idents = optional_check_idents - product_check_idents
    if len(incorrect_check_idents) > 0:
        raise ServiceException("Incorrect checks passed, product_type_name={:s}, incorrect_check_idents={:s}.".format(repr(product_type_name), repr(sorted(incorrect_check_idents))))

    # Compile suite of checks to be performed.
    check_suite = [check
                   for check in product_type["checks"]
                   if check["required"] or check["check_ident"] in optional_check_idents]

    # Run check suite.
    suite_result = {}
    for check in check_suite:
        # Prepare parameteres.
        check_params = {}
        if params is not None:
            check_params.update(params)
        if "parameters" in product_type:
            check_params.update(product_type["parameters"])
        if check["check_ident"] in check_defaults:
            check_params.update(check_defaults[check["check_ident"]])
        if "parameters" in check:
            check_params.update(check["parameters"])

        # Run the check.
        func = get_check_function(check["check_ident"])
        # FIXME: currently check functions use os.path for path manipulation
        #        while upper server stack uses pathlib.
        #        it is encouraged to choose one or another.
        check_result = func(str(filepath), check_params)
        suite_result[check["check_ident"]] = check_result
        if update_result is not None:
            update_result(suite_result)
        if check_result["status"] == "aborted":
            break


class ServiceException(Exception):
    pass
