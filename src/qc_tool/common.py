#!/usr/bin/env python3


import json
import re
import socket
import xml.etree.ElementTree as ET
from importlib import import_module
from os import environ
from pathlib import Path
from shutil import copyfile
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import urlopen
from uuid import uuid4


QC_TOOL_HOME = Path(__file__).parents[2]
QC_TOOL_VERSION_FILEPATH = Path("/etc/qc_tool_version.txt")
QC_TOOL_PRODUCT_DIR = QC_TOOL_HOME.joinpath("product_definitions")
TEST_DATA_DIR = QC_TOOL_HOME.joinpath("testing_data")

API_URL = "http://localhost:8000/api"


WORKER_PORT = 8000
WORKER_ADDR = "0.0.0.0"
WORKER_TOKEN_FILENAME = "worker.token"

JOB_WAITING = "waiting"
JOB_RUNNING = "running"
JOB_OK = "ok"
JOB_PARTIAL = "partial"
JOB_FAILED = "failed"
JOB_ERROR = "error"
JOB_TIMEOUT = "worker timeout"
JOB_LOST = "worker lost"

JOB_INPUT_DIRNAME = "input.d"
JOB_OUTPUT_DIRNAME = "output.d"
JOB_TMP_DIRNAME = "tmp.d"

JOB_RESULT_FILENAME = "result.json"
JOB_REPORT_FILENAME_TPL = "{:s}_report.pdf"

HASH_ALGORITHM = "sha256"
HASH_BUFFER_SIZE = 1024 ** 2

JOB_STEP_SKIPPED = "skipped"
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

PRODUCT_FILENAME_REGEX = re.compile(r"[a-z].*\.json$")

ANNOUNCEMENT_FILENAME = "announcement.txt"

FAILED_ITEMS_LIMIT = 10

JOB_TIME_LIMIT_HOURS = 12

UNKNOWN_REFERENCE_YEAR_LABEL = "ury"

UPDATE_JOB_STATUSES_INTERVAL = 30000
WORKER_ALIVE_TIMEOUT = 20
REFRESH_JOB_STATUSES_BACKGROUND_INTERVAL = 60

#INSPIRE_SERVICE_URL_DEFAULT = "https://sdi.eea.europa.eu/validator/v2/"
INSPIRE_SERVICE_URL_DEFAULT = "http://localhost:8080/validator/v2/"

CONFIG = None


class QCException(Exception):
    pass

def get_timeout(job_time_limit_hours=JOB_TIME_LIMIT_HOURS):
    return {"hours": int(round(job_time_limit_hours)),
            "minutes": int(round(job_time_limit_hours * 60)),
            "seconds": int(round(job_time_limit_hours * 3600))}


def create_worker_token():
    path = CONFIG["work_dir"].joinpath(WORKER_TOKEN_FILENAME)
    Path(CONFIG["work_dir"]).mkdir(parents=True, exist_ok=True)

    if not path.exists():
        path.write_text(str(uuid4()))

def get_worker_token():
    path = CONFIG["work_dir"].joinpath(WORKER_TOKEN_FILENAME)
    if not path.exists():
        create_worker_token()
    stored_token = path.read_text()
    return stored_token

def auth_worker(token):
    stored_token = get_worker_token()
    return token == stored_token

def get_qc_tool_version():
    filepath = QC_TOOL_VERSION_FILEPATH
    if filepath.is_file():
        return filepath.read_text()
    return None

def locate_product_definition(product_ident):
    # The product ident is case insensitive.
    # The product definition is a json file and file name is the same as the product ident.
    for product_dir in CONFIG["product_dirs"]:
        product_filepaths = product_dir.glob("*.json")
        for product_filepath in product_filepaths:
            if product_filepath.stem.lower() == product_ident.lower():
                return product_filepath
    raise QCException("Product definition {:s} has not been found.".format(product_ident))

def load_product_definition(product_ident):
    filepath = locate_product_definition(product_ident)
    data = filepath.read_text()
    product_definition = json.loads(data)
    product_definition["product_ident"] = product_ident
    return product_definition


def validate_skip_steps(skip_steps, product_definition):
    validated_skip_steps = set()
    unskippable_steps = set()
    for skip_step in skip_steps:
        if not (1 <= skip_step <= len(product_definition["steps"])):
            raise QCException("Skip step {:d} is out of range.".format(skip_step))
        if skip_step in validated_skip_steps:
            raise QCException("Duplicit skip step {:d}.".format(skip_step))
        if product_definition["steps"][skip_step - 1]["required"]:
            unskippable_steps.add(skip_step)
        validated_skip_steps.add(skip_step)
    if len(unskippable_steps) > 0:
        raise QCException("The following steps are required and can not be skipped: {:s}.".format(
            ", ".join([str(s) for s in unskippable_steps])))


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

def get_product_definitions():
    product_definitions = []
    # We iterate the dirs in reverse order.
    # In case of identical product ident, the earlier product overrides the later one.
    for product_dir in reversed(CONFIG["product_dirs"]):
        for filepath in product_dir.iterdir():
            if filepath.is_file() and PRODUCT_FILENAME_REGEX.match(filepath.name) is not None:
                product_ident = filepath.stem
                product_definitions.append(product_ident)
    return product_definitions

def compose_job_dir(job_uuid):
    job_subdir_tpl = "job_{:s}"
    job_uuid = job_uuid.lower().replace("-", "")
    job_dir = CONFIG["work_dir"].joinpath("job_{:s}".format(job_uuid))
    return job_dir

def compose_job_stdout_filepath(job_uuid):
    return CONFIG["work_dir"].joinpath(("job.{:s}.stdout").format(job_uuid))

def compose_job_log_filepath(job_uuid):
    job_dir = compose_job_dir(job_uuid)
    return job_dir.joinpath("job.log")

def create_job_dir(job_uuid):
    job_dir = compose_job_dir(job_uuid)
    job_dir.mkdir(parents=True)
    return job_dir

def copy_product_definition_to_job(job_uuid, product_ident):
    src_filepath = locate_product_definition(product_ident)
    dst_filepath = compose_job_dir(job_uuid).joinpath(src_filepath.name)
    copyfile(str(src_filepath), str(dst_filepath))

def load_product_definition_from_job(job_uuid, product_ident):
    # look for the product definition in the job directory.
    # the product definition is a json file and file name is the same as the product ident.
    # the product ident is case insensitive.
    job_dir = compose_job_dir(job_uuid)
    json_filepaths = job_dir.glob("*.json")
    for json_filepath in json_filepaths:
        if json_filepath.stem.lower() == product_ident.lower():
            filepath = json_filepath
            break
    else:
        raise QCException("Product definition file {:s}.json has not been found in the job working directory.".format(product_ident))

    data = filepath.read_text()
    product_definition = json.loads(data)
    product_definition["product_ident"] = product_ident
    return product_definition

def get_job_report_filepath(job_uuid):
    job_result = load_job_result(job_uuid)
    job_dir = compose_job_dir(job_uuid)

    # FIXME:
    # Old version of qc_tool still uses "report.pdf", and there is no "report_filename" in result.json.
    # This part should be cleaned after old jobs using "report.pdf" are removed by service providers.
    job_report_filepath = job_dir.joinpath(job_result.get("report_filename", "report.pdf"))
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
    """Returns short description of the check.

    The qc tool does not take care of historical stages.
    If the check module is missing it is considered that the module has been removed intentionally.
    In such case the description simply states the fact.
    The module may be removed for example due to becoming obsolete.
    """
    try:
        module = import_module(check_ident)
        description = module.DESCRIPTION
    except ModuleNotFoundError:
        description = "Check {:s} does not exist.".format(repr(check_ident))
    return description

def is_system_check(check_ident):
    try:
        module = import_module(check_ident)
        is_system = module.IS_SYSTEM
    except ModuleNotFoundError:
        is_system = False
    return is_system

def prepare_job_blueprint(product_definition):
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
                  "error_message": None,
                  "qc_tool_version": None,
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

def compile_job_form_data(product_ident):
    # There is no job, so return job blueprint.
    product_definition = load_product_definition(product_ident)
    job_form = prepare_job_blueprint(product_definition)
    return job_form

def compile_job_report_data(job_uuid, product_ident=None):
    job_result = None
    try:
        job_result = load_job_result(job_uuid)
    except FileNotFoundError:
        pass
    if job_result is None:
        if product_ident is None:
            raise QCException("Can not make report while both job_result and product_ident are unknown.")
        # Job result does not exist yet so prepare the blueprint.
        product_definition = load_product_definition(product_ident)
        job_report = prepare_job_blueprint(product_definition)
        job_report["job_uuid"] = job_uuid
    else:
        # The job has result document already, so compile the result.
        product_definition = load_product_definition_from_job(job_uuid, job_result["product_ident"])
        job_report = prepare_job_blueprint(product_definition)
        step_defs = job_report["steps"]
        job_report.update(job_result)
        job_report["steps"] = step_defs
        for i, job_step in enumerate(job_result["steps"]):
            job_report["steps"][i].update(job_step)
    return job_report


def load_job_status(job_uuid):
    try:
        job_result = load_job_result(job_uuid)
        job_status = job_result.get("status", JOB_ERROR)
        if job_status is None:
            job_status = JOB_ERROR
    except FileNotFoundError:
        # If the job has already finished there must be correct job result orelse there is some error.
        # FIXME: inform logger.
        job_status = JOB_ERROR
    return job_status


def check_running_job(job_uuid, worker_url, timeout):
    job_status = None
    worker_info = None
    url = urljoin(worker_url, "/jobs/{:s}.json".format(job_uuid))
    try:
        with urlopen(url, timeout=float(timeout)) as resp:
            if resp.status != 200:
                # Bad request or timeout.
                # This situation might be the case of worker timeout / worker unreachable.
                job_status = load_job_status(job_uuid)
                if job_status == JOB_ERROR:
                    return JOB_TIMEOUT
            worker_info = json.loads(resp.read())
    except (TimeoutError, socket.timeout) as ex:
        # This situation might be the case of worker timeout / worker not responding.
        job_status = load_job_status(job_uuid)
        if job_status == JOB_ERROR:
            return JOB_TIMEOUT
    except URLError as ex:
        # Cannot connect to worker, maybe the job had already finished and then the worker was shutdown.
        job_status = load_job_status(job_uuid)
        if job_status == JOB_ERROR:
            return JOB_LOST
    if worker_info is None:
        # The job has already finished so load status from job result.
        job_status = load_job_status(job_uuid)
    return job_status


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
    * API_URL;
    * UPDATE_JOB_STATUSES;
    * UPDATE_JOB_STATUSES_INTERVAL;
    * WORKER_ALIVE_TIMEOUT;


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
    config["announcement_path"] = config["frontend_db_path"].with_name(ANNOUNCEMENT_FILENAME)
    config["submission_dir"] = environ.get("SUBMISSION_DIR", "")
    if config["submission_dir"] == "":
        config["submission_dir"] = None
    else:
        config["submission_dir"] = Path(config["submission_dir"])

    # Parameters consumed by worker.
    config["pull_job_url"] = environ.get("PULL_JOB_URL", "http://qc_tool_frontend:8000/pull_job")

    ## Access to postgis.
    config["pg_host"] = environ.get("PG_HOST", "127.0.0.1")
    config["pg_port"] = int(environ.get("PG_PORT", 5432))
    config["pg_user"] = environ.get("PG_USER", "qc_job")
    config["pg_database"] = environ.get("PG_DATABASE", "qc_tool_db")

    ## Debugging parameters.
    config["leave_schema"] = environ.get("LEAVE_SCHEMA", "no") == "yes"
    config["leave_jobdir"] = environ.get("LEAVE_JOBDIR", "no") == "yes"

    config["skip_inspire_check"] = environ.get("SKIP_INSPIRE_CHECK", "no") == "yes"

    # Logo customization.
    config["show_logo"] = environ.get("SHOW_LOGO", "yes") == "yes"

    # api url
    config["api_url"] = environ.get("API_URL", API_URL)

    # update job statuses in the ui. 
    config["update_job_statuses"] = environ.get("UPDATE_JOB_STATUSES", "yes") == "yes"
    config["update_job_statuses_interval"] = environ.get(
        "UPDATE_JOB_STATUSES_INTERVAL", UPDATE_JOB_STATUSES_INTERVAL)

    # timeout for checking if a worker is alive.
    config["worker_alive_timeout"] = environ.get(
        "WORKER_ALIVE_TIMEOUT", WORKER_ALIVE_TIMEOUT)

    # timeout for updating job statuses in the background thread
    config["refresh_job_statuses_background_interval"] = environ.get(
        "REFRESH_JOB_STATUSES_BACKGROUND_INTERVAL", REFRESH_JOB_STATUSES_BACKGROUND_INTERVAL)

    # INSPIRE validator service URL
    config["inspire_service_url"] = environ.get(
        "INSPIRE_SERVICE_URL", INSPIRE_SERVICE_URL_DEFAULT
    )

    return config

CONFIG = setup_config()
