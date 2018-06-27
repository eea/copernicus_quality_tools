#!/usr/bin/env python3


import json
import re
from os import environ
from os.path import normpath
from pathlib import Path


# FIXME: such normalization should be removed in python3.6.
QC_TOOL_HOME = Path(normpath(str(Path(__file__).joinpath("../../.."))))
PRODUCT_DIR = QC_TOOL_HOME.joinpath("product_definitions")
CHECK_DEFAULTS_FILEPATH = PRODUCT_DIR.joinpath("_check_defaults.json")
TEST_DATA_DIR = QC_TOOL_HOME.joinpath("testing_data")
DB_FUNCTION_DIR = QC_TOOL_HOME.joinpath("src/qc_tool/wps/db_functions")
DB_FUNCTION_SCHEMA_NAME = "qc_function"

INCOMING_DIR = Path("/mnt/incomming")
WPS_DIR = Path("/mnt/wps")
WORK_DIR = Path("/mnt/work")

PRODUCT_FILENAME_REGEX = re.compile(r"[a-z].*\.json$")

CHECK_FUNCTION_DESCRIPTIONS = {
    "import2pg": "Import layers into PostGIS database.",
    "v1": "File format is allowed.",
    "v2": "File names match file naming conventions.",
    "v3": "Attribute table contains specified attributes.",
    "v4": "CRS of layer expressed as EPSG code match reference EPSG code.",
    "v5": "Unique identifier check.",
    "v6": "Valid codes check.",
    "v7": "(no description)",
    "v8": "No multipart polygons.",
    "v9": "(no description)",
    "v10": "(no description)",
    "v11": "Minimum mapping unit check.",
    "v12": "(no description)",
    "v13": "There are no overlapping polygons.",
    "v14": "No neighbouring polygons with the same code.",
    "r1": "File format is allowed.",
    "r2": "File names match file naming conventions.",
    "r3": "Attribute table contains specified attributes.",
    "r4": "EPSG code of file CRS match reference EPSG code.",
    "r5": "Pixel size must be equal to given value.",
    "r6": "Raster origin check.",
    "r7": "Raster has specified bit depth data type.",
    "r8": "Compression type check.",
    "r9": "Pixel values check.",
    "r10": "In the mapped area are no NoData pixels.",
    "r11": "Minimum mapping unit check.",
    "r12": "(no description)",
    "r13": "(no description)",
    "r14": "Raster has a color table.",
    "r15": "Colors in the color table match product specification."}

SYSTEM_CHECK_FUNCTIONS = ["import2pg"]

CONFIG = None


def strip_prefix(check_ident):
    check_ident = check_ident.split(".")[-1]
    return check_ident

def load_product_definitions(product_ident):
    """
    Loads all definitions of a particuar product.

    The return value is a list of definitions.
    The first item of the list is a definition of a passed product.
    Then definitions of every subproduct follow sorted by full ident name.

    Every check ident is made prefixed by subproduct ident.
    """
    product_paths = [path for path in PRODUCT_DIR.iterdir()
                     if PRODUCT_FILENAME_REGEX.match(path.name) is not None
                     and path.name.startswith("{:s}.".format(product_ident))]
    product_paths = sorted(product_paths, key=lambda x: x.stem)
    product_definitions = []
    for filepath in product_paths:
        product_ident = filepath.stem
        product_definition = filepath.read_text()
        product_definition = json.loads(product_definition)
        if "checks" in product_definition:
            for check in product_definition["checks"]:
                full_check_ident = "{:s}.{:s}".format(product_ident, check["check_ident"])
                check["check_ident"] = full_check_ident
        product_definitions.append(product_definition)

    return product_definitions

def compile_product_infos():
    """
    Compiles dictionary of product infos.

    The product ident becomes the key.
    The items consist of main products only.
    The value represents product info and is formed as:
    {"description: "<product description>",
     "checks": [("<product_ident>.<function_name>", "<function_description>", <is_required>, <is_system>), ...]}
    """
    product_paths = [path for path in PRODUCT_DIR.iterdir()
                     if PRODUCT_FILENAME_REGEX.match(path.name) is not None]
    product_paths = sorted(product_paths, key=lambda x: x.stem)
    product_infos = {}
    for filepath in product_paths:
        product_ident = filepath.stem
        main_product_ident = product_ident.split(".", maxsplit=1)[0]
        product_definition = filepath.read_text()
        product_definition = json.loads(product_definition)

        # Add main product to product infos.
        if main_product_ident not in product_infos:
            product_infos[main_product_ident] = {"description": product_definition["description"],
                                                 "checks": []}

        # Append checks to main product info.
        # Inject full check identifier and system flag.
        if "checks" in product_definition:
            for check in product_definition["checks"]:
                short_check_ident = check["check_ident"]
                full_check_ident = "{:s}.{:s}".format(product_ident, short_check_ident)
                check_info = (full_check_ident,
                              CHECK_FUNCTION_DESCRIPTIONS[check["check_ident"]],
                              check["required"],
                              short_check_ident in SYSTEM_CHECK_FUNCTIONS)
                product_infos[main_product_ident]["checks"].append(check_info)

    return product_infos

def load_check_defaults():
    check_defaults = CHECK_DEFAULTS_FILEPATH.read_text()
    check_defaults = json.loads(check_defaults)
    return check_defaults

def setup_config():
    """
    Environment variables consumed by wps:
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
    * WPS_URL;
    """
    config = {}

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
