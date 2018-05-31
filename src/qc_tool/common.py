#!/usr/bin/env python3


import json
import re
from os.path import normpath
from pathlib import Path


# FIXME: such normalization should be removed in python3.6.
QC_TOOL_HOME = Path(normpath(str(Path(__file__).joinpath("../../.."))))
PRODUCT_TYPES_DIR = QC_TOOL_HOME.joinpath("product_types")
CHECK_DEFAULTS_FILEPATH = PRODUCT_TYPES_DIR.joinpath("_check_defaults.json")
TEST_DATA_DIR = QC_TOOL_HOME.joinpath("testing_data")

PRODUCT_TYPE_REGEX = re.compile(r"[a-z].*\.json$")


def load_product_type_definition(product_type_name):
    filename = "{:s}.json".format(product_type_name)
    filepath = PRODUCT_TYPES_DIR.joinpath(filename)
    product_type_definition = filepath.read_text()
    product_type_definition = json.loads(product_type_definition)
    return product_type_definition

def get_all_product_type_names():
    product_type_names = [path.stem
                          for path in PRODUCT_TYPES_DIR.iterdir()
                          if PRODUCT_TYPE_REGEX.match(path.name) is not None]
    return product_type_names

def load_all_product_type_definitions():
    product_type_definitions = {}
    product_type_names = get_all_product_type_names()
    for product_type_name in product_type_names:
        product_type_definition = load_product_type_definition(product_type_name)
        product_type_definitions[product_type_name] = product_type_definition
    return product_type_definitions

def load_check_defaults():
    check_defaults = CHECK_DEFAULTS_FILEPATH.read_text()
    check_defaults = json.loads(check_defaults)
    return check_defaults
