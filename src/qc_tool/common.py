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

JOB_INPUT_DIRNAME = "input.d"
JOB_OUTPUT_DIRNAME = "output.d"
JOB_TMP_DIRNAME = "tmp.d"

HASH_ALGORITHM = "sha256"
HASH_BUFFER_SIZE = 1024 ** 2

STATUS_RUNNING_LABEL = "running"
STATUS_SKIPPED_LABEL = "skipped"
STATUS_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

PRODUCT_FILENAME_REGEX = re.compile(r"[a-z].*\.json$")

FAILED_ITEMS_LIMIT = 10

UNKNOWN_REFERENCE_YEAR_LABEL = "ury"

CHECK_FUNCTION_DESCRIPTIONS = {
    "v_unzip": "Unzips the delivery file.",
    "v_import2pg": "Import layers into PostGIS database.",
    "v1_clc": "Naming is in accord with specification (clc product).",
    "v1_n2k": "Naming is in accord with specification (n2k product).",
    "v1_rpz": "Naming is in accord with specification (rpz product).",
    "v1_ua_gdb": "Naming is in accord with specification, geodatabase delivery.",
    "v1_ua_shp": "Naming is in accord with specification, shapefile delivery.",
    "v2": "File format is correct.",
    "v3": "Attribute table contains prescribed attributes.",
    "v4": "CRS of layer expressed as EPSG code match reference EPSG code.",
    "v5": "Unique identifier check.",
    "v6": "Valid codes check.",
    "v7": "(no description)",
    "v8": "No multipart polygons.",
    "v9": "(no description)",
    "v10": "(no description)",
    "v11": "Minimum mapping unit check.",
    "v11_ua": "Minimum mapping unit check.",
    "v12": "(no description)",
    "v13": "There are no overlapping polygons.",
    "v14": "No neighbouring polygons with the same code.",
    "r_unzip": "Unzips the source file.",
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

SYSTEM_CHECK_FUNCTIONS = ["r_unzip", "v_import2pg", "v_unzip"]

CONFIG = None


def strip_prefix(check_ident):
    check_ident = check_ident.split(".")[-1]
    return check_ident

def load_product_definition(product_ident):
    filepath = PRODUCT_DIR.joinpath("{:s}.json".format(product_ident))
    product_definition = filepath.read_text()
    product_definition = json.loads(product_definition)
    return product_definition

def get_product_descriptions():
    filepaths = [path for path in PRODUCT_DIR.iterdir()
                 if PRODUCT_FILENAME_REGEX.match(path.name) is not None]
    product_descriptions = {}
    for filepath in filepaths:
        product_ident = filepath.stem
        product_definition = filepath.read_text()
        product_definition = json.loads(product_definition)
        product_description = product_definition["description"]
        product_descriptions[product_ident] = product_description
    return product_descriptions

def prepare_empty_job_status(product_ident):
    """
    Prepare status structure to be later filled by check results.

    {"product_ident": <product ident>,
     "description: <product description>,
     "user_name": <>,
     "job_start_date": <>,
     "filename": <>,
     "hash": <>,
     "reference_year": <>,
     "job_uuid": <>,
     "exception": <>,
     "checks": [{"check_ident": <full check ident>,
                 "check_description": <>,
                 "required": <>,
                 "system": <>,
                 "status": <>,
                 "messages": <>,
                 "attachment_filenames": <>}, ...]}
    """
    filepath = PRODUCT_DIR.joinpath("{:s}.json".format(product_ident))
    product_definition = filepath.read_text()
    product_definition = json.loads(product_definition)
    status = {"product_ident": product_ident,
              "description": product_definition["description"],
              "user_name": None,
              "job_start_date": None,
              "job_finish_date": None,
              "filename": None,
              "hash": None,
              "reference_year": None,
              "job_uuid": None,
              "exception": None,
              "checks": []}
    for check in product_definition["checks"]:
        short_check_ident = strip_prefix(check["check_ident"])
        check_item = {"check_ident": check["check_ident"],
                      "description": CHECK_FUNCTION_DESCRIPTIONS[short_check_ident],
                      "required": check["required"],
                      "system": short_check_ident in SYSTEM_CHECK_FUNCTIONS,
                      "status": None,
                      "messages": None,
                      "attachment_filenames": None}
        status["checks"].append(check_item)
    return status

def load_check_defaults():
    check_defaults = CHECK_DEFAULTS_FILEPATH.read_text()
    check_defaults = json.loads(check_defaults)
    return check_defaults

def compose_job_dir(job_uuid):
    job_subdir_tpl = "job_{:s}"
    job_uuid = str(job_uuid).lower().replace("-", "")
    job_dir = CONFIG["work_dir"].joinpath("job_{:s}".format(job_uuid))
    return job_dir

def compose_job_status_filepath(job_uuid):
    job_dir = compose_job_dir(job_uuid)
    job_status_filepath = job_dir.joinpath("status.json")
    return job_status_filepath

def compose_wps_status_filepath(job_uuid):
    wps_status_filename = "{:s}.xml".format(str(job_uuid))
    wps_status_filepath = CONFIG["wps_output_dir"].joinpath(wps_status_filename)
    return wps_status_filepath

def compose_attachment_filepath(job_uuid, filename):
    job_dir = compose_job_dir(job_uuid)
    filepath = job_dir.joinpath(JOB_OUTPUT_DIRNAME).joinpath(filename)
    return filepath

def get_all_wps_uuids():
    status_document_regex = re.compile(r"[a-z0-9-]{36}\.xml")
    wps_output_dir = CONFIG["wps_output_dir"]
    wps_uuids = [path.stem
                 for path in wps_output_dir.iterdir()
                 if status_document_regex.match(path.name) is not None]
    return wps_uuids

def setup_config():
    """
    Environment variables consumed by wps:
    * BOUNDARY_DIR;
    * INCOMING_DIR;
    * WPS_DIR;
    * WORK_DIR,
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
    * SUBMISSION_DIR;
    * FRONTEND_DB_PATH;
    * WPS_DIR;
    * WORK_DIR;
    * WPS_URL;
    """
    config = {}

    # Parameters consumed by frontend.
    config["frontend_db_path"] = Path(environ.get("FRONTEND_DB_PATH", "/var/lib/qc_tool/frontend.sqlite3"))
    config["submission_dir"] = environ.get("SUBMISSION_DIR", "")
    if config["submission_dir"] == "":
        config["submission_dir"] = None
    else:
        config["submission_dir"] = Path(config["submission_dir"])

    # Parameters common to both frontend and wps.
    config["boundary_dir"] = Path(environ.get("BOUNDARY_DIR", "/mnt/qc_tool_boundary/boundary"))
    config["incoming_dir"] = Path(environ.get("INCOMING_DIR", TEST_DATA_DIR))
    config["wps_dir"] = Path(environ.get("WPS_DIR", "/mnt/qc_tool_volume/wps"))
    config["work_dir"] = Path(environ.get("WORK_DIR", "/mnt/qc_tool_volume/work"))
    config["wps_output_dir"] = config["wps_dir"].joinpath("output")

    # Wps server port to listen on.
    config["wps_port"] = int(environ.get("WPS_PORT", 5000))

    # Access to wps service.
    config["wps_url"] = environ.get("WPS_URL", "http://localhost:{:d}/wps".format(config["wps_port"]))
    config["wps_output_url"] = environ.get("WPS_OUTPUT_URL", "http://localhost:{:d}/output".format(config["wps_port"]))

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
