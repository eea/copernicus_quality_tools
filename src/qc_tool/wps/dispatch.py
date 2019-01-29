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
from qc_tool.common import compose_job_status_filepath
from qc_tool.common import load_check_defaults
from qc_tool.common import load_product_definition
from qc_tool.common import prepare_empty_job_status
from qc_tool.common import strip_prefix
from qc_tool.wps.manager import create_connection_manager
from qc_tool.wps.manager import create_jobdir_manager
from qc_tool.wps.registry import get_check_function


def write_job_status(filepath, data):
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

def compile_check_suite(product_ident, product_definition, optional_check_idents):
    optional_check_idents = set(optional_check_idents)
    defined_optional_check_idents = {check["check_ident"]
                                     for check in product_definition["checks"] if not check["required"]}

    # Ensure passed optional checks take part in product.
    incorrect_check_idents = optional_check_idents - defined_optional_check_idents
    if len(incorrect_check_idents) > 0:
        raise QCException("Incorrect checks passed.", {"product_ident": product_ident,
                                                       "incorrect_check_idents": incorrect_check_idents})

    # Compile check suite.
    skipped_idents = defined_optional_check_idents - optional_check_idents
    check_suite = [check
                   for check in product_definition["checks"]
                   if check["required"] or check["check_ident"] in optional_check_idents]
    return check_suite, skipped_idents

def dump_error_table(connection_manager, error_table_name, src_table_name, pg_fid_name, output_dir):
    connection = connection_manager.get_connection()
    (dsn, schema) = connection_manager.get_dsn_schema()
    conn_string = "PG:{:s} active_schema={:s}".format(dsn, schema)
    csv_filepath = output_dir.joinpath("{:s}.csv".format(error_table_name))
    shp_filepath = output_dir.joinpath("{:s}.shp".format(error_table_name))
    zip_filepath = output_dir.joinpath("{:s}.zip".format(error_table_name))

    # Extract column names of the error table.
    with closing(connection.cursor()) as cursor:
        cursor.execute("SELECT * FROM {:s};".format(error_table_name))
        column_names = [column.name for column in cursor.description]
        column_names.sort()

    # Prepare sql command for ogr2ogr.
    if len(column_names) == 0:
        raise QCException("Error table {:s} has no column.".format(error_table_name))
    if len(column_names) == 1:
        # Error table contains one column of feature fids.
        ogr2ogr_sql = ("SELECT *"
                       " FROM {src_table_name:s}"
                       " WHERE {pg_fid_name:s} IN"
                        " (SELECT {column_0:s}"
                         " FROM {error_table_name:s})"
                       " ORDER BY {pg_fid_name:s};")
        ogr2ogr_sql = ogr2ogr_sql.format(src_table_name=src_table_name,
                                         pg_fid_name=pg_fid_name,
                                         column_0=column_names[0],
                                         error_table_name=error_table_name)
    elif len(column_names) == 2:
        # Error table contains two columns representing pairs of feature fids.
        ogr2ogr_sql = ("SELECT *"
                       " FROM {src_table_name:s}"
                       " WHERE {pg_fid_name:s} IN"
                        " (SELECT {column_0:s}"
                         " FROM {error_table_name:s} "
                         " UNION"
                         " SELECT {column_1:s} "
                         " FROM {error_table_name:s})"
                       " ORDER BY {pg_fid_name:s};")
        ogr2ogr_sql = ogr2ogr_sql.format(src_table_name=src_table_name,
                                         pg_fid_name=pg_fid_name,
                                         column_0=column_names[0],
                                         column_1=column_names[1],
                                         error_table_name=error_table_name)
    else:
        raise QCException("Error table {:s} has unexpected columns: {:s}.".format(error_table_name,
                                                                                  repr(column_names)))
    # Export error table content into csv.
    sql = "SELECT * FROM {:s} ORDER BY {:s};".format(error_table_name, ", ".join(column_names))
    with closing(connection.cursor()) as cursor:
        cursor.execute(sql)
        with closing(open(str(csv_filepath), 'w')) as csv_file:
            csv_writer = csv.writer(csv_file)
            csv_writer.writerows(cursor.fetchall())

    # Export error features into shp.
    args = ["ogr2ogr",
            "-f", "ESRI Shapefile",
            "-sql", ogr2ogr_sql,
            str(shp_filepath),
            conn_string]
    run(args)

    # Gather all files to be zipped.
    filepaths_to_zip = [f for f in output_dir.iterdir() if f.stem == error_table_name]

    # Ensure csv and shp files are present.
    if csv_filepath not in filepaths_to_zip:
        raise QCException("Dumped csv file {:s} is missing.".format(csv_filepath))
    if shp_filepath not in filepaths_to_zip:
        raise QCException("Dumped shp file {:s} is missing.".format(shp_filepath))

    # Zip the files.
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
            conn_string]
    run(args)

    # Gather all files to be zipped.
    filepaths_to_zip = [f for f in output_dir.iterdir() if f.stem == table_name]

    # Ensure shp files are present.
    if shp_filepath not in filepaths_to_zip:
        raise QCException("Dumped shp file {:s} is missing.".format(shp_filepath))

    # Zip the files.
    with ZipFile(str(zip_filepath), "w") as zf:
        for filepath in filepaths_to_zip:
            zf.write(str(filepath), filepath.name)

    # Remove zipped files.
    for filepath in filepaths_to_zip:
        if filepath.is_file():
            filepath.unlink()

    return zip_filepath.name

def dispatch(job_uuid, user_name, filepath, product_ident, optional_check_idents, update_status_func=None):
    with ExitStack() as exit_stack:
        # Prepare job directory structure.
        status_filepath = compose_job_status_filepath(job_uuid)
        job_status = prepare_empty_job_status(product_ident)
        jobdir_manager = exit_stack.enter_context(create_jobdir_manager(job_uuid))
        try:
            # Set up initial job status items.
            job_status["user_name"] = user_name
            job_status["job_start_date"] = datetime.utcnow().strftime(STATUS_TIME_FORMAT)
            job_status["filename"] = filepath.name
            job_status["job_uuid"] = job_uuid
            job_status["optional_check_idents"] = list(optional_check_idents)
            job_status["hash"] = make_signature(filepath)
            job_status_check_idx = {check["check_ident"]: check for check in job_status["checks"]}

            # Read configurations.
            check_defaults = load_check_defaults()
            product_definition = load_product_definition(product_ident)

            check_suite, skipped_idents = compile_check_suite(product_ident, product_definition, optional_check_idents)
            for skipped_ident in skipped_idents:
                job_status_check_idx[skipped_ident]["status"] = STATUS_SKIPPED_LABEL

            # Prepare initial job params.
            job_params = {}
            job_params["connection_manager"] = exit_stack.enter_context(create_connection_manager(job_uuid))
            job_params["tmp_dir"] = jobdir_manager.tmp_dir
            job_params["output_dir"] = jobdir_manager.output_dir
            job_params["filepath"] = filepath
            job_params["boundary_dir"] = CONFIG["boundary_dir"]

            for check_nr, check in enumerate(check_suite):

                # Update status.json.
                job_status_check_idx[check["check_ident"]]["status"] = STATUS_RUNNING_LABEL
                write_job_status(status_filepath, job_status)

                # Update status at wps.
                if update_status_func is not None:
                    percent_done = check_nr / len(check_suite) * 100
                    update_status_func(check["check_ident"], percent_done)

                # Prepare parameters.
                check_params = {}
                check_params.update(check_defaults["globals"])
                short_check_ident = strip_prefix(check["check_ident"])
                if short_check_ident in check_defaults["checks"]:
                    check_params.update(check_defaults["checks"][short_check_ident])
                if "parameters" in product_definition:
                    check_params.update(product_definition["parameters"])
                if "parameters" in check:
                    check_params.update(check["parameters"])
                check_params.update(job_params)
                check_params["check_ident"] = check["check_ident"]

                # Run the check.
                check_status = CheckStatus()
                func = get_check_function(check["check_ident"])
                func(check_params, check_status)

                # Set the check result into the job status.
                job_check_status = job_status_check_idx[check["check_ident"]]
                job_check_status["status"] = check_status.status
                job_check_status["messages"] = check_status.messages
                job_check_status["attachment_filenames"] = check_status.attachment_filenames.copy()

                # Export error tables to csv and zipped shapefile.
                for (error_table_name, src_table_name, pg_fid_name) in check_status.error_table_infos:
                    attachment_filename = dump_error_table(job_params["connection_manager"],
                                                           error_table_name,
                                                           src_table_name,
                                                           pg_fid_name,
                                                           jobdir_manager.output_dir)
                    job_check_status["attachment_filenames"].append(attachment_filename)

                # Export full tables to zipped shapefile.
                for table_name in check_status.full_table_names:
                    attachment_filename = dump_full_table(job_params["connection_manager"],
                                                          table_name,
                                                          jobdir_manager.output_dir)
                    job_check_status["attachment_filenames"].append(attachment_filename)

                # Update job status properties.
                job_status.update(check_status.status_properties)

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
                job_status["exception"] = format_exc()
            job_status["job_finish_date"] = datetime.utcnow().strftime(STATUS_TIME_FORMAT)
            write_job_status(status_filepath, job_status)

    return job_status


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

    def failed(self):
        if self.status != "aborted":
            self.status = "failed"

    def aborted(self):
        self.status = "aborted"

    def cancelled(self):
        if self.status != "aborted":
            self.status = "cancelled"

    def is_aborted(self):
        return self.status == "aborted"

    def add_message(self, message, failed=True):
        self.messages.append(message)
        if failed:
            self.failed()

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
