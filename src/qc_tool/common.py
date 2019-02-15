#!/usr/bin/env python3


import json
import re
from os import environ
from os.path import normpath
from pathlib import Path


# FIXME: such normalization should be removed in python3.6.
QC_TOOL_HOME = Path(normpath(str(Path(__file__).joinpath("../../.."))))
PRODUCT_DIR = QC_TOOL_HOME.joinpath("product_definitions")
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
    "v4": "EPSG code of the layer is in the list of allowed codes.",
    "v4_clc": "EPSG code of the layer match EPSG code of the boundary layer.",
    "v5": "Unique identifier check.",
    "v6": "Valid codes check.",
    "v7": "Non-probable changes.",
    "v8": "No multipart polygons.",
    "v9": "The geometries are valid.",
    "v10": "Completeness.",
    "v10_unit": "Completeness, multiple boundary units.",
    "v11_clc_change": "Minimum mapping unit check, Corine Land Cover change layer.",
    "v11_clc_status": "Minimum mapping unit check, Corine Land Cover status layer.",
    "v11_n2k": "Minimum mapping unit check, Natura 2000.",
    "v11_rpz": "Minimum mapping unit check, Riparian zones.",
    "v11_ua_change": "Minimum mapping unit check, Urban Atlas change layer.",
    "v11_ua_status": "Minimum mapping unit check, Urban Atlas status layer.",
    "v12": "Minimum mapping width.",
    "v12_ua": "Minimum mapping width (ua product).",
    "v13": "There are no overlapping polygons.",
    "v14": "No neighbouring polygons with the same code.",
    "v14_rpz": "No neighbouring polygons with the same code, Riparian zones.",
    "v15": "Vector metadata is compliant with INSPIRE specifications.",
    "r_unzip": "Unzips the source file.",
    "r1": "File format is allowed.",
    "r2": "File names match file naming conventions.",
    "r3": "Attribute table contains specified attributes.",
    "r4": "EPSG code of the raster file is in the list of allowed codes.",
    "r5": "Pixel size must be equal to given value.",
    "r6": "Raster origin check.",
    "r7": "Raster has specified bit depth data type.",
    "r8": "Compression type check.",
    "r9": "Pixel values check.",
    "r10": "Raster completeness check.",
    "r11": "Minimum mapping unit check.",
    "r12": "Raster metadata is compliant with INSPIRE specifications.",
    "r13": "Colors in the color table match product specification."}

SYSTEM_CHECK_FUNCTIONS = ["r_unzip", "v_import2pg", "v_unzip"]

CONFIG = None


def strip_prefix(check_ident):
    check_ident = check_ident.split(".")[-1]
    return check_ident

def load_product_definition(product_ident):
    filepath = PRODUCT_DIR.joinpath("{:s}.json".format(product_ident))
    product_definition = filepath.read_text()
    product_definition = json.loads(product_definition)
    product_definition["product_ident"] = product_ident
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

def prepare_job_result(product_definition):
    """
    Prepare job result structure.

    {"product_ident": <product ident>,
     "description: <product description>,
     "user_name": <>,
     "job_start_date": <>,
     "job_finish_date": <>,
     "filename": <>,
     "hash": <>,
     "reference_year": <>,
     "job_uuid": <>,
     "exception": <>,
     "steps": [{"step_nr": <ordinal number of the step>
                "check_ident": <full check ident>,
                "check_description": <>,
                "required": <>,
                "system": <>,
                "status": <>,
                "messages": <>,
                "attachment_filenames": <>}, ...]}
    """
    job_result = {"product_ident": product_definition["product_ident"],
                  "description": product_definition["description"],
                  "user_name": None,
                  "job_start_date": None,
                  "job_finish_date": None,
                  "filename": None,
                  "hash": None,
                  "reference_year": None,
                  "job_uuid": None,
                  "exception": None,
                  "steps": []}
    for step_nr, step_def in enumerate(product_definition["steps"], start=1):
        short_check_ident = strip_prefix(step_def["check_ident"])
        step_result = {"step_nr": step_nr,
                       "check_ident": step_def["check_ident"],
                       "description": CHECK_FUNCTION_DESCRIPTIONS[short_check_ident],
                       "layers": step_def.get("parameters", {}).get("layers", None),
                       "required": step_def["required"],
                       "system": short_check_ident in SYSTEM_CHECK_FUNCTIONS,
                       "status": None,
                       "messages": None,
                       "attachment_filenames": None}
        job_result["steps"].append(step_result)
    return job_result

def compose_job_dir(job_uuid):
    job_subdir_tpl = "job_{:s}"
    job_uuid = str(job_uuid).lower().replace("-", "")
    job_dir = CONFIG["work_dir"].joinpath("job_{:s}".format(job_uuid))
    return job_dir

def compose_job_report_filepath(job_uuid):
    job_dir = compose_job_dir(job_uuid)
    job_report_filepath = job_dir.joinpath("report.pdf")
    return job_report_filepath

def compose_job_result_filepath(job_uuid):
    job_dir = compose_job_dir(job_uuid)
    job_result_filepath = job_dir.joinpath("result.json")
    return job_result_filepath

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
    config["boundary_dir"] = Path(environ.get("BOUNDARY_DIR", "/mnt/qc_tool_boundary/boundaries"))
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

    config["skip_inspire_check"] = environ.get("SKIP_INSPIRE_CHECK", "no") == "yes"

    return config

CONFIG = setup_config()
