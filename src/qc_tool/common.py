#!/usr/bin/env python3


import json
import re
import time
from os import environ
from os.path import normpath
from pathlib import Path
from shutil import copyfile


# FIXME: such normalization should be removed in python3.6.
QC_TOOL_HOME = Path(normpath(str(Path(__file__).joinpath("../../.."))))
PRODUCT_DIR = QC_TOOL_HOME.joinpath("product_definitions")
TEST_DATA_DIR = QC_TOOL_HOME.joinpath("testing_data")


JOB_ERROR = "error"
JOB_FAILED = "failed"
JOB_OK = "ok"
JOB_PARTIAL = "partial"

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

CHECK_FUNCTION_DESCRIPTIONS = {
    "qc_tool.vector.unzip": "Unzips the delivery file.",
    "qc_tool.vector.import2pg": "Import layers into PostGIS database.",
    "qc_tool.vector.naming_clc": "Naming is in accord with specification (clc product).",
    "qc_tool.vector.naming_n2k": "Naming is in accord with specification (n2k product).",
    "qc_tool.vector.naming_rpz": "Naming is in accord with specification (rpz product).",
    "qc_tool.vector.naming_ua_gdb": "Naming is in accord with specification, geodatabase delivery.",
    "qc_tool.vector.naming_ua_shp": "Naming is in accord with specification, shapefile delivery.",
    "qc_tool.vector.format": "File format is correct.",
    "qc_tool.vector.attribute": "Attribute table contains prescribed attributes.",
    "qc_tool.vector.epsg": "EPSG code of the layer is in the list of allowed codes.",
    "qc_tool.vector.epsg_clc": "EPSG code of the layer match EPSG code of the boundary layer.",
    "qc_tool.vector.unique": "Unique identifier check.",
    "qc_tool.vector.enum": "Valid codes check.",
    "qc_tool.vector.non_probable_changes": "Non-probable changes.",
    "qc_tool.vector.singlepart": "No multipart polygons.",
    "qc_tool.vector.geometry": "The geometries are valid.",
    "qc_tool.vector.gap": "Completeness.",
    "qc_tool.vector.gap_unit": "Completeness, multiple boundary units.",
    "qc_tool.vector.mmu_clc_change": "Minimum mapping unit check, Corine Land Cover change layer.",
    "qc_tool.vector.mmu_clc_status": "Minimum mapping unit check, Corine Land Cover status layer.",
    "qc_tool.vector.mmu_n2k": "Minimum mapping unit check, Natura 2000.",
    "qc_tool.vector.mmu_rpz": "Minimum mapping unit check, Riparian zones.",
    "qc_tool.vector.mmu_ua_change": "Minimum mapping unit check, Urban Atlas change layer.",
    "qc_tool.vector.mmu_ua_status": "Minimum mapping unit check, Urban Atlas status layer.",
    "qc_tool.vector.mmw": "Minimum mapping width.",
    "qc_tool.vector.mmw_ua": "Minimum mapping width (ua product).",
    "qc_tool.vector.overlap": "There are no overlapping polygons.",
    "qc_tool.vector.neighbour": "No neighbouring polygons with the same code.",
    "qc_tool.vector.neighbour_rpz": "No neighbouring polygons with the same code, Riparian zones.",
    "qc_tool.vector.inspire": "Vector metadata is compliant with INSPIRE specifications.",
    "qc_tool.raster.unzip": "Unzips the source file.",
    "qc_tool.raster.format": "File format is allowed.",
    "qc_tool.raster.naming": "File names match file naming conventions.",
    "qc_tool.raster.attribute": "Attribute table contains specified attributes.",
    "qc_tool.raster.epsg": "EPSG code of the raster file is in the list of allowed codes.",
    "qc_tool.raster.pixel_size": "Pixel size must be equal to given value.",
    "qc_tool.raster.origin": "Raster origin check.",
    "qc_tool.raster.bit_depth": "Raster has specified bit depth data type.",
    "qc_tool.raster.compress": "Compression type check.",
    "qc_tool.raster.value": "Pixel values check.",
    "qc_tool.raster.gap": "Raster completeness check.",
    "qc_tool.raster.mmu": "Minimum mapping unit check.",
    "qc_tool.raster.inspire": "Raster metadata is compliant with INSPIRE specifications.",
    "qc_tool.raster.color": "Colors in the color table match product specification."}

SYSTEM_CHECK_FUNCTIONS = ["qc_tool.raster.unzip",
                          "qc_tool.vector.import2pg",
                          "qc_tool.vector.unzip"]

CONFIG = None


class QCException(Exception):
    pass


def load_product_definition(product_ident):
    filepath = PRODUCT_DIR.joinpath("{:s}.json".format(product_ident))
    data = filepath.read_text()
    product_definition = json.loads(data)
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

def compose_job_dir(job_uuid):
    job_subdir_tpl = "job_{:s}"
    job_uuid = job_uuid.lower().replace("-", "")
    job_dir = CONFIG["work_dir"].joinpath("job_{:s}".format(job_uuid))
    return job_dir

def copy_product_definition_to_job(job_uuid, product_ident):
    src_filepath = PRODUCT_DIR.joinpath("{:s}.json".format(product_ident))
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

def has_job_expired(job_uuid, timeout=JOB_EXPIRE_TIMEOUT):
    job_dir = compose_job_dir(job_uuid)
    job_result_filepath = job_dir.joinpath(JOB_RESULT_FILENAME)
    job_timestamp = job_result_filepath.stat().st_mtime
    now_timestamp = time.time()
    return job_timestamp + timeout < now_timestamp

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
                       "description": CHECK_FUNCTION_DESCRIPTIONS[step_def["check_ident"]],
                       "layers": step_def.get("parameters", {}).get("layers", None),
                       "required": step_def["required"],
                       "system": step_def["check_ident"] in SYSTEM_CHECK_FUNCTIONS,
                       "status": None,
                       "messages": None,
                       "attachment_filenames": None}
        job_report["steps"].append(step_report)
    return job_report

def compile_job_report(job_uuid=None, product_ident=None):
    job_result = None
    if job_uuid is not None:
        try:
            job_result = load_job_result(job_uuid)
        except FileNotFoundError:
            pass
    if job_result is None:
        if product_ident is None:
            raise QCException("Missing product_ident while there is no job result for job {:s}.".format(job_uuid))
        product_definition = load_product_definition(product_ident)
    else:
        product_definition = load_product_definition_from_job(job_uuid, job_result["product_ident"])
    job_report = prepare_job_report(product_definition)
    if job_result is None:
        # WPS status already exists, however job result does not yet.
        if job_uuid is not None:
            job_report["job_uuid"] = job_uuid
    else:
        step_defs = job_report["steps"]
        job_report.update(job_result)
        job_report["steps"] = step_defs
        for i, job_step in enumerate(job_result["steps"]):
            job_report["steps"][i].update(job_step)
    return job_report

def load_wps_status(job_uuid):
    wps_status_filename = "{:s}.xml".format(str(job_uuid))
    wps_status_filepath = CONFIG["wps_output_dir"].joinpath(wps_status_filename)
    wps_status = wps_status_filepath.read_text()
    return wps_status

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
