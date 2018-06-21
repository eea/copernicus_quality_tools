#!/usr/bin/env python3


import json
import re
from os import environ
from os.path import normpath
from pathlib import Path

from qc_tool.wps.registry import get_descriptions


# FIXME: such normalization should be removed in python3.6.
QC_TOOL_HOME = Path(normpath(str(Path(__file__).joinpath("../../.."))))
PRODUCT_DIR = QC_TOOL_HOME.joinpath("product_types")
CHECK_DEFAULTS_FILEPATH = PRODUCT_DIR.joinpath("_check_defaults.json")
TEST_DATA_DIR = QC_TOOL_HOME.joinpath("testing_data")
DB_FUNCTION_DIR = QC_TOOL_HOME.joinpath("src/qc_tool/wps/db_functions")
DB_FUNCTION_SCHEMA_NAME = "qc_function"

PRODUCT_NAME_REGEX = re.compile(r"[a-z].*\.json$")

CONFIG = None


def load_product_definition(product_name):
    filename = "{:s}.json".format(product_name)
    filepath = PRODUCT_DIR.joinpath(filename)
    product_definition = filepath.read_text()
    product_definition = json.loads(product_definition)
    return product_definition

def compile_product_infos():
    """
    Compiles dictionary of product infos.

    Every value of product info is in the form:
    {"description: "<product description>",
     "checks": [("<function_name>", "<function_description>", <is_required>), ...]}
    """
    product_paths = [path for path in PRODUCT_DIR.iterdir()
                     if PRODUCT_NAME_REGEX.match(path.name) is not None]
    check_descriptions = get_descriptions()
    product_infos = {}
    for filepath in product_paths:
        product_ident = filepath.stem
        product_definition = filepath.read_text()
        product_definition = json.loads(product_definition)
        product_description = product_definition["description"]
        product_checks = [(check["check_ident"], check_descriptions[check["check_ident"]], check["required"])
                          for check in product_definition["checks"]]
        product_infos[product_ident] = {"description": product_description, "checks": product_checks}

    return product_infos

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
    * WPS_PORT;
    * WPS_URL;
    * WPS_OUTPUT_URL;
    * PG_HOST;
    * PG_PORT;
    * PG_USER;
    * PG_DATABASE;
    * LEAVE_SCHEMA;
    * JOBDIR_EXIST_OK;
    * LEAVE_JOBDIR;

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
    config["wps_url"] = environ.get("WPS_URL", "http://localhost:{:d}/wps".format(config["wps_port"]))
    config["wps_output_url"] = environ.get("WPS_OUTPUT_URL", "http://localhost:{:d}/wps/output".format(config["wps_port"]))

    # Access to postgis.
    config["pg_host"] = environ.get("PG_HOST", "qc_tool_postgis")
    config["pg_port"] = int(environ.get("PG_PORT", 5432))
    config["pg_user"] = environ.get("PG_USER", "qc_job")
    config["pg_database"] = environ.get("PG_DATABASE", "qc_tool_db")

    # Debugging parameters.
    config["leave_schema"] = environ.get("LEAVE_SCHEMA", "no") == "yes"
    config["jobdir_exist_ok"] = environ.get("JOBDIR_EXIST_OK", "no") == "yes"
    config["leave_jobdir"] = environ.get("LEAVE_JOBDIR", "no") == "yes"

    return config

CONFIG = setup_config()
