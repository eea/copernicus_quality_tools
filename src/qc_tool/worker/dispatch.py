#!/usr/bin/env python3


import hashlib
import logging
from contextlib import ExitStack
from datetime import datetime
from functools import partial
from importlib import import_module
from subprocess import run
from sys import exc_info
from traceback import format_exc
from signal import signal, alarm, SIGALRM
from time import time

from qc_tool.common import get_qc_tool_version, validate_skip_steps
from qc_tool.common import CONFIG
from qc_tool.common import copy_product_definition_to_job
from qc_tool.common import HASH_ALGORITHM
from qc_tool.common import HASH_BUFFER_SIZE
from qc_tool.common import JOB_ERROR
from qc_tool.common import JOB_FAILED
from qc_tool.common import JOB_OK
from qc_tool.common import JOB_PARTIAL
from qc_tool.common import JOB_REPORT_FILENAME_TPL
from qc_tool.common import JOB_STEP_SKIPPED
from qc_tool.common import load_product_definition
from qc_tool.common import QCException
from qc_tool.common import TIME_FORMAT
from qc_tool.common import store_job_result
from qc_tool.common import get_timeout
from qc_tool.worker.report import generate_pdf_report
from qc_tool.worker.manager import create_connection_manager
from qc_tool.worker.manager import create_jobdir_manager


log = logging.getLogger(__name__)

class TimedOutExc(Exception):
    pass
    #print ("The check has failed due to a timeout.")

def signal_handler(signum, frame):
    raise TimedOutExc()

def make_signature(filepath):
    h = hashlib.new(HASH_ALGORITHM)
    with open(str(filepath), "rb") as f:
        for buf in iter(partial(f.read, HASH_BUFFER_SIZE), b''):
            h.update(buf)
    return h.hexdigest()

def dump_error_table(connection_manager, error_table_name, src_table_name, pg_fid_name, output_dir, src_filename_stem=None):
    (dsn, schema) = connection_manager.get_dsn_schema()
    conn_string = "PG:{:s} active_schema={:s}".format(dsn, schema)
    gpkg_filepath = output_dir.joinpath("{:s}.gpkg".format(error_table_name))
    if src_filename_stem is not None:
        gpkg_filepath = output_dir.joinpath("{:s}_{:s}.gpkg".format(src_filename_stem, error_table_name))

    # Export error features into geopackage.
    sql_params = {"fid_name": pg_fid_name,
                  "src_table": src_table_name,
                  "error_table": error_table_name}
    sql = ("SELECT st.*\n"
           "FROM\n"
           " {error_table} AS et\n"
           " INNER JOIN {src_table} AS st ON et.{fid_name} = st.{fid_name}\n"
           "ORDER BY st.{fid_name};")
    sql = sql.format(**sql_params)
    args = ["ogr2ogr",
            "-f", "GPKG",
            "-sql", sql,
            "-nln", error_table_name,
            str(gpkg_filepath),
            conn_string]
    run(args)
    return gpkg_filepath.name

def dump_full_table(connection_manager, table_name, output_dir, src_filename_stem=None):
    connection = connection_manager.get_connection()
    (dsn, schema) = connection_manager.get_dsn_schema()
    conn_string = "PG:{:s} active_schema={:s}".format(dsn, schema)
    gpkg_filepath = output_dir.joinpath("{:s}.gpkg".format(table_name))
    if src_filename_stem is not None:
        gpkg_filepath = output_dir.joinpath("{:s}_{:s}.gpkg".format(src_filename_stem, table_name))

    # Export features into geopackage.
    args = ["ogr2ogr",
            "-f", "GPKG",
            "-nln", table_name,
            str(gpkg_filepath),
            conn_string,
            table_name]
    run(args)
    return gpkg_filepath.name


def dispatch(job_uuid, user_name, filepath, product_ident, skip_steps=tuple(), s3_params=None):

    task_timeout = get_timeout()
    with ExitStack() as exit_stack:
        # Prepare job variables.
        product_definition = load_product_definition(product_ident)
        validate_skip_steps(skip_steps, product_definition)
        jobdir_manager = exit_stack.enter_context(create_jobdir_manager(job_uuid))
        job_report_filepath = jobdir_manager.job_dir.joinpath(JOB_REPORT_FILENAME_TPL.format(filepath.stem))
        try:
            # Make duplicate of product definition in job dir.
            copy_product_definition_to_job(job_uuid, product_ident)

            # Set up initial job result items.
            job_result = {"job_uuid": job_uuid,
                          "product_ident": product_ident,
                          "user_name": user_name,
                          "job_start_date": datetime.utcnow().strftime(TIME_FORMAT),
                          "filename": filepath.name,
                          "report_filename": job_report_filepath.name,
                          "error_message": None,
                          "qc_tool_version": get_qc_tool_version(),
                          "steps": []}

            if s3_params:
                # FIXME make correct signature also in case of S3 files.
                pass
            else:
                job_result["hash"] = make_signature(filepath)

            # Store initial job result.
            # This way we announce that the job has started.
            store_job_result(job_result)

            # Prepare initial job params.
            job_params = {}
            job_params["connection_manager"] = exit_stack.enter_context(create_connection_manager(job_uuid))
            job_params["tmp_dir"] = jobdir_manager.tmp_dir
            job_params["output_dir"] = jobdir_manager.output_dir
            job_params["filepath"] = filepath
            job_params["boundary_dir"] = CONFIG["boundary_dir"]
            job_params["skip_inspire_check"] = CONFIG["skip_inspire_check"]
            job_params["s3"] = {}

            # Add S3 job params if specified.
            if s3_params:
                job_params["s3"] = s3_params

            for step_nr, step_def in enumerate(product_definition["steps"], start=1):

                step_result = {"check_ident": step_def["check_ident"]}

                # Replace by unzip checks by s3_download checks for s3 deliveries
                if s3_params and step_def["check_ident"] in ("qc_tool.vector.unzip", "qc_tool.raster.unzip"):
                    replaced_check_ident = step_def["check_ident"].replace("unzip", "s3_download")
                    replaced_check_description = "Data can be downloaded from S3" #TODO load description from module
                    step_def["check_ident"] = replaced_check_ident
                    step_result = {"check_ident": step_def["check_ident"],
                                   "description": replaced_check_description}

                # Skip this step.
                if step_nr in skip_steps:
                    step_result["status"] = JOB_STEP_SKIPPED
                    job_result["steps"].append(step_result)
                    store_job_result(job_result)
                    continue

                # Prepare parameters for this step.
                step_params = {}
                step_params.update(step_def.get("parameters", {}))
                step_params.update(job_params)
                step_params["step_nr"] = step_nr
                step_params["check_is_required"] = step_def.get("required", {})

                # Run the step.
                check_status = CheckStatus()
                check_module = import_module(step_def["check_ident"])

                # time limit implementation
                signal(SIGALRM, signal_handler)
                alarm(task_timeout["seconds"])

                # Set the check result into the job status.
                try:
                    start = time()
                    check_module.run_check(step_params, check_status)
                    stop = time()
                    task_runtime = stop - start
                    if check_status.status == "aborted" and task_runtime > task_timeout["seconds"]:
                        check_status.aborted("The check has failed due to a timeout "
                                             "(the implemented timeout is {to} seconds).".format(
                            to=str(task_timeout["seconds"])))
                except TimedOutExc as e:
                    if step_params["check_is_required"]:
                        check_status.aborted("The check has failed due to a timeout "
                                               "(the implemented timeout is {to} seconds).".format(to=str(task_timeout["seconds"])))

                    else:
                        check_status.failed("The check has failed due to a timeout "
                                             "(the implemented timeout is {to} seconds).".format(to=str(task_timeout["seconds"])))

                step_result["status"] = check_status.status
                step_result["messages"] = check_status.messages
                step_result["attachment_filenames"] = check_status.attachment_filenames.copy()

                # Export error tables.
                for (error_table_name, src_table_name, pg_fid_name) in check_status.error_table_infos:
                    attachment_filename = dump_error_table(job_params["connection_manager"],
                                                           error_table_name,
                                                           src_table_name,
                                                           pg_fid_name,
                                                           jobdir_manager.output_dir,
                                                           filepath.stem)
                    step_result["attachment_filenames"].append(attachment_filename)

                # Export full tables.
                for table_name in check_status.full_table_names:
                    attachment_filename = dump_full_table(job_params["connection_manager"],
                                                          table_name,
                                                          jobdir_manager.output_dir,
                                                          filepath.stem)
                    step_result["attachment_filenames"].append(attachment_filename)

                # Update job status properties.
                job_result.update(check_status.status_properties)

                # Update job params.
                job_params.update(check_status.status_properties)
                job_params.update(check_status.params)

                # Update stored job result.
                job_result["steps"].append(step_result)
                store_job_result(job_result)
                log.info("Result of the job step {:d}:{:s} has been stored.".format(step_nr, step_def["check_ident"]))

                # Abort validation job.
                if check_status.is_aborted():
                    break

        finally:
            # Finalize the job.
            (ex_type, ex_obj, tb_obj) = exc_info()
            if tb_obj is not None:
                log.exception("Job has been interrupted by an exception.")
                job_result["error_message"] = format_exc()
            job_result["job_finish_date"] = datetime.utcnow().strftime(TIME_FORMAT)
            step_statuses = set(job_step["status"] for job_step in job_result["steps"])
            if job_result["error_message"] is not None:
                job_result["status"] = JOB_ERROR
            elif "aborted" in step_statuses:
                job_result["status"] = JOB_FAILED
            elif "failed" in step_statuses:
                job_result["status"] = JOB_FAILED
            elif JOB_STEP_SKIPPED in step_statuses:
                job_result["status"] = JOB_PARTIAL
            elif "cancelled" in step_statuses:
                job_result["status"] = JOB_FAILED
            else:
                job_result["status"] = JOB_OK
            store_job_result(job_result)
            log.info("Job result has been completed.")
            generate_pdf_report(job_report_filepath, job_uuid)
            log.info("Job report has been generated.")

    return job_result


class CheckStatus():
    def __init__(self):
        self.status = "ok"
        self.messages = []
        self.error_table_infos = []
        self.full_table_names = []
        self.attachment_filenames = []
        self.params = {}
        self.status_properties = {}

    def aborted(self, message):
        self.messages.append(message)
        self.status = "aborted"

    def failed(self, message):
        self.messages.append(message)
        if self.status != "aborted":
            self.status = "failed"

    def cancelled(self, message):
        self.messages.append(message)
        if self.status not in ("aborted", "failed"):
            self.status = "cancelled"

    def info(self, message):
        self.messages.append(message)

    def is_aborted(self):
        return self.status == "aborted"

    def add_error_table(self, error_table_name, src_table_name, pg_fid_name):
        self.error_table_infos.append((error_table_name, src_table_name, pg_fid_name))

    def add_full_table(self, table_name):
        self.full_table_names.append(table_name)

    def add_attachment(self, filename):
        self.attachment_filenames.append(filename)

    def add_params(self, params_dict):
        self.params.update(params_dict)

    def set_status_property(self, key, value):
        self.status_properties[key] = value

    def __repr__(self):
        members_tpl = ("status={:s}"
                       ", messages={:s}"
                       ", error_table_infos={:s}"
                       ", attachment_filenames={:s}"
                       ", params={:s}"
                       ", status_properties={:s}")
        members = members_tpl.format(repr(self.status),
                                     repr(self.messages),
                                     repr(self.error_table_infos),
                                     repr(self.attachment_filenames),
                                     repr(self.params),
                                     repr(self.status_properties))
        ret = "{:s}({:s})".format(self.__class__.__name__, members)
        return ret
