#!/usr/bin/env python3


import json
import re
from os import environ
from os.path import normpath
from pathlib import Path


# FIXME: such normalization should be removed in python3.6.
QC_TOOL_HOME = Path(normpath(str(Path(__file__).joinpath("../../.."))))
PRODUCT_TYPES_DIR = QC_TOOL_HOME.joinpath("product_types")
CHECK_DEFAULTS_FILEPATH = PRODUCT_TYPES_DIR.joinpath("_check_defaults.json")
TEST_DATA_DIR = QC_TOOL_HOME.joinpath("testing_data")

PRODUCT_TYPE_REGEX = re.compile(r"[a-z].*\.json$")

CONFIG = None


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

def setup_config():
    """
    Environment variables consumed by wps:
    * INCOMING_DIR;
    * WPS_DIR;
    * WORK_DIR;
    * WPS_HOST;
    * WPS_PORT;
    * WPS_URL;
    * WPS_OUTPUT_URL;
    * PG_HOST;
    * PG_PORT;
    * PG_USER;
    * PG_DATABASE;

    Environment variables consumed by frontend:
    * INCOMING_DIR;
    * WPS_URL;
    """
    config = {}

    # Parameters common to both frontend and wps.
    config["incoming_dir"] = Path(environ.get("INCOMING_DIR", TEST_DATA_DIR))
    config["wps_dir"] = Path(environ.get("WPS_DIR", "/mnt/wps"))
    config["work_dir"] = Path(environ.get("WORK_DIR", "/mnt/work"))

    # Wps server port to listen on.
    config["wps_port"] = int(environ.get("WPS_PORT", 5000))

    # Access to wps service.
    config["wps_host"] = environ.get("WPS_HOST", "qc_tool_wps")
    config["wps_url"] = environ.get("WPS_URL", "http://{:s}:{:d}/wps".format(config["wps_host"], config["wps_port"]))
    config["wps_output_url"] = environ.get("WPS_OUTPUT_URL", "http://{:s}:{:d}/wps/output".format(config["wps_host"], config["wps_port"]))

    # Access to postgis.
    config["pg_host"] = environ.get("PG_HOST", "qc_tool_postgis")
    config["pg_port"] = int(environ.get("PG_PORT", 5432))
    config["pg_user"] = environ.get("PG_USER", "qc_job")
    config["pg_database"] = environ.get("PG_DATABASE", "qc_tool_db")

    # Debugging parameters.
    config["leave_schema"] = bool(environ.get("LEAVE_SCHEMA", False))

    return config

CONFIG = setup_config()
