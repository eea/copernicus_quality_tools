#!/usr/bin/env python3


import csv
import hashlib
import json
from contextlib import closing
from contextlib import ExitStack
from datetime import datetime
from functools import partial
from subprocess import run
from sys import exc_info
from traceback import format_exc
from zipfile import ZipFile

from qc_tool.common import CONFIG
from qc_tool.common import HASH_ALGORITHM
from qc_tool.common import HASH_BUFFER_SIZE
from qc_tool.common import STATUS_RUNNING_LABEL
from qc_tool.common import STATUS_SKIPPED_LABEL
from qc_tool.common import STATUS_TIME_FORMAT
from qc_tool.common import compose_job_report_filepath
from qc_tool.common import compose_job_result_filepath
from qc_tool.common import load_product_definition
from qc_tool.common import prepare_job_result
from qc_tool.wps.report import write_pdf_report
from qc_tool.wps.manager import create_connection_manager
from qc_tool.wps.manager import create_jobdir_manager
from qc_tool.wps.registry import get_check_function


def write_job_result(filepath, data):
    # We write the status to pre file and then rename it in order to eliminate
    # race condition if somebody just reads the file.
    pre_filepath = filepath.with_name("{:s}.pre".format(filepath.name))
    text = json.dumps(data)
    pre_filepath.write_text(text)
    pre_filepath.rename(filepath)

def make_signature(filepath):
    h = hashlib.new(HASH_ALGORITHM)
    with open(str(filepath), "rb") as f:
        for buf in iter(partial(f.read, HASH_BUFFER_SIZE), b''):
            h.update(buf)
    return h.hexdigest()

def dump_error_table(connection_manager, error_table_name, src_table_name, pg_fid_name, output_dir):
    (dsn, schema) = connection_manager.get_dsn_schema()
    conn_string = "PG:{:s} active_schema={:s}".format(dsn, schema)
    shp_filepath = output_dir.joinpath("{:s}.shp".format(error_table_name))
    zip_filepath = output_dir.joinpath("{:s}.zip".format(error_table_name))

    # Export error features into shp.
    sql_params = {"fid_name": pg_fid_name,
                  "src_table": src_table_name,
                  "error_table": error_table_name}
    sql = ("SELECT *"
           " FROM {src_table}"
           " WHERE {fid_name} IN (SELECT {fid_name} FROM {error_table})"
           " ORDER BY {fid_name};")
    sql = sql.format(**sql_params)
    args = ["ogr2ogr",
            "-f", "ESRI Shapefile",
            "-sql", sql,
            str(shp_filepath),
            conn_string]
    run(args)

    # Zip the files.
    filepaths_to_zip = [f for f in output_dir.iterdir() if f.stem == error_table_name]
    if shp_filepath not in filepaths_to_zip:
        raise QCException("Dumped shp file {:s} is missing.".format(str(shp_filepath)))
    with ZipFile(str(zip_filepath), "w") as zf:
        for filepath in filepaths_to_zip:
            zf.write(str(filepath), filepath.name)

    # Remove zipped files.
    for filepath in filepaths_to_zip:
        filepath.unlink()

    return zip_filepath.name

def dump_full_table(connection_manager, table_name, output_dir):
    connection = connection_manager.get_connection()
    (dsn, schema) = connection_manager.get_dsn_schema()
    conn_string = "PG:{:s} active_schema={:s}".format(dsn, schema)
    shp_filepath = output_dir.joinpath("{:s}.shp".format(table_name))
    zip_filepath = output_dir.joinpath("{:s}.zip".format(table_name))

    # Export geom features into shp.
    args = ["ogr2ogr",
            "-f", "ESRI Shapefile",
            str(shp_filepath),
            conn_string,
            table_name]
    run(args)

    # Gather all files to be zipped.
    filepaths_to_zip = [f for f in output_dir.iterdir() if f.stem == table_name]

    # Ensure shp files are present.
    if shp_filepath not in filepaths_to_zip:
        raise QCException("Dumped shp file {:s} is missing.".format(str(shp_filepath)))

    # Zip the files.
    with ZipFile(str(zip_filepath), "w") as zf:
        for filepath in filepaths_to_zip:
            zf.write(str(filepath), filepath.name)

    # Remove zipped files.
    for filepath in filepaths_to_zip:
        if filepath.is_file():
            filepath.unlink()

    return zip_filepath.name

def validate_skip_steps(skip_steps, product_definition):
    validated_skip_steps = set()
    for skip_step in skip_steps:
        if not (1 <= skip_step <= len(product_definition["steps"])):
            raise QCException("Skip step {:d} is out of range.".format(skip_step))
        if skip_step in validated_skip_steps:
            raise QCException("Duplicit skip step {:d}.".format(skip_step))
        if product_definition["steps"][skip_step - 1]["required"]:
            raise QCException("Required step {:d} can not be skipped.".format(skip_step))
        validated_skip_steps.add(skip_step)

def dispatch(job_uuid, user_name, filepath, product_ident, skip_steps=tuple(), update_status_func=None):
    with ExitStack() as exit_stack:
        # Prepare job variables.
        product_definition = load_product_definition(product_ident)
        validate_skip_steps(skip_steps, product_definition)
        job_result_filepath = compose_job_result_filepath(job_uuid)
        job_report_filepath = compose_job_report_filepath(job_uuid)
        job_result = prepare_job_result(product_definition)
        jobdir_manager = exit_stack.enter_context(create_jobdir_manager(job_uuid))
        try:
            # Set up initial job result items.
            job_result["user_name"] = user_name
            job_result["job_start_date"] = datetime.utcnow().strftime(STATUS_TIME_FORMAT)
            job_result["filename"] = filepath.name
            job_result["job_uuid"] = job_uuid
            job_result["hash"] = make_signature(filepath)

            # Prepare initial job params.
            job_params = {}
            job_params["connection_manager"] = exit_stack.enter_context(create_connection_manager(job_uuid))
            job_params["tmp_dir"] = jobdir_manager.tmp_dir
            job_params["output_dir"] = jobdir_manager.output_dir
            job_params["filepath"] = filepath
            job_params["boundary_dir"] = CONFIG["boundary_dir"]
            job_params["skip_inspire_check"] = CONFIG["skip_inspire_check"]

            for step_result, step_def in zip(job_result["steps"], product_definition["steps"]):

                # Update status.json.
                step_result["status"] = STATUS_RUNNING_LABEL
                write_job_result(job_result_filepath, job_result)

                # Update status at wps.
                if update_status_func is not None:
                    percent_done = (step_result["step_nr"] - 1) / len(job_result["steps"]) * 100
                    update_status_func(step_result["step_nr"], percent_done)

                # Skip this step.
                if step_result["step_nr"] in skip_steps:
                    step_result["status"] = STATUS_SKIPPED_LABEL
                    continue

                # Prepare parameters.
                step_params = {}
                step_params.update(step_def.get("parameters", {}))
                step_params.update(job_params)

                # Run the step.
                check_status = CheckStatus()
                func = get_check_function(step_result["check_ident"])
                func(step_params, check_status)

                # Set the check result into the job status.
                step_result["status"] = check_status.status
                step_result["messages"] = check_status.messages
                step_result["attachment_filenames"] = check_status.attachment_filenames.copy()

                # Export error tables to csv and zipped shapefile.
                for (error_table_name, src_table_name, pg_fid_name) in check_status.error_table_infos:
                    attachment_filename = dump_error_table(job_params["connection_manager"],
                                                           error_table_name,
                                                           src_table_name,
                                                           pg_fid_name,
                                                           jobdir_manager.output_dir)
                    step_result["attachment_filenames"].append(attachment_filename)

                # Export full tables to zipped shapefile.
                for table_name in check_status.full_table_names:
                    attachment_filename = dump_full_table(job_params["connection_manager"],
                                                          table_name,
                                                          jobdir_manager.output_dir)
                    step_result["attachment_filenames"].append(attachment_filename)

                # Update job status properties.
                job_result.update(check_status.status_properties)

                # Abort validation job.
                if check_status.is_aborted():
                    break

                # Update job params.
                job_params.update(check_status.status_properties)
                job_params.update(check_status.params)

        finally:
            # Update status.json finally and record exception if raised.
            (ex_type, ex_obj, tb_obj) = exc_info()
            if tb_obj is not None:
                job_result["exception"] = format_exc()
            job_result["job_finish_date"] = datetime.utcnow().strftime(STATUS_TIME_FORMAT)
            write_job_result(job_result_filepath, job_result)
            write_pdf_report(job_report_filepath, job_result)

    return job_result


class QCException(Exception):
    pass


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
