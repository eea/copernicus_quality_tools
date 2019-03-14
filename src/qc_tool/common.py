#!/usr/bin/env python3


import json
import re
import time
import xml.etree.ElementTree as ET
from importlib import import_module
from os import environ
from os.path import normpath
from pathlib import Path
from shutil import copyfile


QC_TOOL_HOME = Path(__file__).parents[2]
QC_TOOL_PRODUCT_DIR = QC_TOOL_HOME.joinpath("product_definitions")
TEST_DATA_DIR = QC_TOOL_HOME.joinpath("testing_data")

WORKER_PORT = 8000
WORKER_ADDR = "0.0.0.0"

JOB_WAITING = "waiting"
JOB_RUNNING = "running"
JOB_OK = "ok"
JOB_PARTIAL = "partial"
JOB_FAILED = "failed"
JOB_ERROR = "error"
JOB_EXPIRED = "expired"

JOB_EXPIRE_TIMEOUT = 43200

JOB_INPUT_DIRNAME = "input.d"
JOB_OUTPUT_DIRNAME = "output.d"
JOB_TMP_DIRNAME = "tmp.d"

JOB_RESULT_FILENAME = "result.json"
JOB_REPORT_FILENAME = "report.pdf"

HASH_ALGORITHM = "sha256"
HASH_BUFFER_SIZE = 1024 ** 2

JOB_STEP_SKIPPED = "skipped"
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

PRODUCT_FILENAME_REGEX = re.compile(r"[a-z].*\.json$")

FAILED_ITEMS_LIMIT = 10

UNKNOWN_REFERENCE_YEAR_LABEL = "ury"

CONFIG = None


class QCException(Exception):
    pass


def locate_product_definition(product_ident):
    for product_dir in CONFIG["product_dirs"]:
        filepath = product_dir.joinpath("{:s}.json".format(product_ident))
        if filepath.is_file():
            return filepath
    raise QCException("Product definition {:s} has not been found.".format(product_ident))

def load_product_definition(product_ident):
    filepath = locate_product_definition(product_ident)
    data = filepath.read_text()
    product_definition = json.loads(data)
    product_definition["product_ident"] = product_ident
    return product_definition

def get_product_descriptions():
    product_descriptions = {}
    # We iterate the dirs in reverse order.
    # In case of identical product ident, the earlier product overrides the later one.
    for product_dir in reversed(CONFIG["product_dirs"]):
        for filepath in product_dir.iterdir():
            if PRODUCT_FILENAME_REGEX.match(filepath.name) is not None:
                product_ident = filepath.stem
                product_definition = filepath.read_text()
                product_definition = json.loads(product_definition)
                product_description = product_definition["description"]
                product_descriptions[product_ident] = product_description
    return product_descriptions

def compose_job_dir(job_uuid):
    job_subdir_tpl = "job_{:s}"
    job_uuid = job_uuid.lower().replace("-", "")
    job_dir = CONFIG["work_dir"].joinpath("job_{:s}".format(job_uuid))
    return job_dir

def copy_product_definition_to_job(job_uuid, product_ident):
    src_filepath = locate_product_definition(product_ident)
    dst_filepath = compose_job_dir(job_uuid).joinpath(src_filepath.name)
    copyfile(str(src_filepath), str(dst_filepath))

def load_product_definition_from_job(job_uuid, product_ident):
    filepath = compose_job_dir(job_uuid).joinpath("{:s}.json".format(product_ident))
    data = filepath.read_text()
    product_definition = json.loads(data)
    product_definition["product_ident"] = product_ident
    return product_definition

def compose_job_report_filepath(job_uuid):
    job_dir = compose_job_dir(job_uuid)
    job_report_filepath = job_dir.joinpath(JOB_REPORT_FILENAME)
    return job_report_filepath

def load_job_result(job_uuid):
    job_dir = compose_job_dir(job_uuid)
    job_result_filepath = job_dir.joinpath(JOB_RESULT_FILENAME)
    job_result = job_result_filepath.read_text()
    job_result = json.loads(job_result)
    return job_result

def store_job_result(job_result):
    job_result_data = json.dumps(job_result)
    job_dir = compose_job_dir(job_result["job_uuid"])
    # The job result is repeatedly rewritten every job step.
    # In order to eliminate distortion of job result just being read
    # we write the new content into adjacent file which we
    # then rename.
    job_result_filepath = job_dir.joinpath(JOB_RESULT_FILENAME)
    job_result_filepath_pre = job_dir.joinpath(JOB_RESULT_FILENAME + ".pre")
    job_result_filepath_pre.write_text(job_result_data)
    job_result_filepath_pre.rename(job_result_filepath)

def get_check_description(check_ident):
    module = import_module(check_ident)
    description = module.DESCRIPTION
    return description

def is_system_check(check_ident):
    module = import_module(check_ident)
    is_system = module.IS_SYSTEM
    return is_system

def prepare_job_report(product_definition):
    job_report = {"job_uuid": None,
                  "status": None,
                  "product_ident": product_definition["product_ident"],
                  "description": product_definition["description"],
                  "user_name": None,
                  "job_start_date": None,
                  "job_finish_date": None,
                  "filename": None,
                  "hash": None,
                  "reference_year": None,
                  "exception": None,
                  "steps": []}
    for step_nr, step_def in enumerate(product_definition["steps"], start=1):
        step_report = {"step_nr": step_nr,
                       "check_ident": step_def["check_ident"],
                       "description": get_check_description(step_def["check_ident"]),
                       "layers": step_def.get("parameters", {}).get("layers", None),
                       "required": step_def["required"],
                       "system": is_system_check(step_def["check_ident"]),
                       "status": None,
                       "messages": None,
                       "attachment_filenames": None}
        job_report["steps"].append(step_report)
    return job_report

def compile_job_report(job_uuid=None, product_ident=None):
    if job_uuid is None:
        # There is no job, so return job blueprint.
        product_definition = load_product_definition(product_ident)
        job_report = prepare_job_report(product_definition)
    else:
        # The job exists already.
        job_result = None
        try:
            job_result = load_job_result(job_uuid)
        except FileNotFoundError:
            pass
        if job_result is None:
            # The job has no result document yet, so return job blueprint.
            if product_ident is None:
                raise QCException("Missing product_ident while there is no job result for job {:s}.".format(job_uuid))
            product_definition = load_product_definition(product_ident)
            job_report = prepare_job_report(product_definition)
            job_report["job_uuid"] = job_uuid
        else:
            # The job has result document already, so return the result.
            product_definition = load_product_definition_from_job(job_uuid, job_result["product_ident"])
            job_report = prepare_job_report(product_definition)
            step_defs = job_report["steps"]
            job_report.update(job_result)
            job_report["steps"] = step_defs
            for i, job_step in enumerate(job_result["steps"]):
                job_report["steps"][i].update(job_step)
    return job_report

def compose_attachment_filepath(job_uuid, filename):
    job_dir = compose_job_dir(job_uuid)
    filepath = job_dir.joinpath(JOB_OUTPUT_DIRNAME).joinpath(filename)
    return filepath

def setup_config():
    """
    Environment variables consumed by frontend:
    * PRODUCT_DIRS;
    * BOUNDARY_DIR;
    * INCOMING_DIR;
    * WORK_DIR;
    * SUBMISSION_DIR;
    * FRONTEND_DB_PATH;
    * SHOW_LOGO;

    Environment variables consumed by worker:
    * PRODUCT_DIRS;
    * BOUNDARY_DIR;
    * INCOMING_DIR;
    * PULL_JOB_URL;
    * WORK_DIR,
    * PG_HOST;
    * PG_PORT;
    * PG_USER;
    * PG_DATABASE;
    * LEAVE_SCHEMA;
    * JOBDIR_EXIST_OK;
    * LEAVE_JOBDIR;
    * SHOW_LOGO;
    """
    config = {}

    # Parameters common to frontend and worker.

    if "PRODUCT_DIRS" in environ:
        _product_dirs = environ.get("PRODUCT_DIRS")
        _product_dirs = _product_dirs.split(":")
        _product_dirs = [Path(d) for d in _product_dirs]
        config["product_dirs"] = _product_dirs
    else:
        config["product_dirs"] = [QC_TOOL_PRODUCT_DIR]
    config["boundary_dir"] = Path(environ.get("BOUNDARY_DIR", "/mnt/qc_tool_boundary/boundaries"))
    config["incoming_dir"] = Path(environ.get("INCOMING_DIR", TEST_DATA_DIR))
    config["work_dir"] = Path(environ.get("WORK_DIR", "/mnt/qc_tool_volume/work"))

    # Parameters consumed by frontend.

    config["frontend_db_path"] = Path(environ.get("FRONTEND_DB_PATH", "/var/lib/qc_tool/frontend.sqlite3"))
    config["submission_dir"] = environ.get("SUBMISSION_DIR", "")
    if config["submission_dir"] == "":
        config["submission_dir"] = None
    else:
        config["submission_dir"] = Path(config["submission_dir"])

    # Parameters consumed by worker.
    config["pull_job_url"] = environ.get("PULL_JOB_URL", "http://qc_tool_frontend:8000/pull_job")

    ## Access to postgis.
    config["pg_host"] = environ.get("PG_HOST", "qc_tool_postgis")
    config["pg_port"] = int(environ.get("PG_PORT", 5432))
    config["pg_user"] = environ.get("PG_USER", "qc_job")
    config["pg_database"] = environ.get("PG_DATABASE", "qc_tool_db")

    ## Debugging parameters.
    config["leave_schema"] = environ.get("LEAVE_SCHEMA", "no") == "yes"
    config["jobdir_exist_ok"] = environ.get("JOBDIR_EXIST_OK", "no") == "yes"
    config["leave_jobdir"] = environ.get("LEAVE_JOBDIR", "no") == "yes"

    config["skip_inspire_check"] = environ.get("SKIP_INSPIRE_CHECK", "no") == "yes"

    # Logo customization.
    config["show_logo"] = environ.get("SHOW_LOGO", "yes") == "yes"

    return config

CONFIG = setup_config()
