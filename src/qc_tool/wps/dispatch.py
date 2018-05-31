#!/usr/bin/env python3


from contextlib import closing
from os import environ
from pathlib import Path

from psycopg2 import connect

from qc_tool.wps.registry import get_check_function

import qc_tool.wps.common_check.dummy
import qc_tool.wps.raster_check.r1
import qc_tool.wps.raster_check.r2
import qc_tool.wps.raster_check.r4
import qc_tool.wps.vector_check.import2pg
import qc_tool.wps.vector_check.v1
import qc_tool.wps.vector_check.v2
import qc_tool.wps.vector_check.v3
import qc_tool.wps.vector_check.v4
import qc_tool.wps.vector_check.v11
from qc_tool.common import CONFIG
from qc_tool.common import load_product_type_definition
from qc_tool.common import load_check_defaults


def dispatch(job_uuid, filepath, product_type_name, optional_check_idents, update_result_func=None):
    # Read configurations.
    check_defaults = load_check_defaults()
    product_type = load_product_type_definition(product_type_name)

    # Prepare check idents.
    product_check_idents = set(check["check_ident"] for check in product_type["checks"])
    optional_check_idents = set(optional_check_idents)

    # Ensure passed optional checks take part in product type.
    incorrect_check_idents = optional_check_idents - product_check_idents
    if len(incorrect_check_idents) > 0:
        raise ServiceException("Incorrect checks passed, product_type_name={:s}, incorrect_check_idents={:s}.".format(repr(product_type_name), repr(sorted(incorrect_check_idents))))

    # Compile suite of checks to be performed.
    check_suite = [check
                   for check in product_type["checks"]
                   if check["required"] or check["check_ident"] in optional_check_idents]

    # Run with postgre connection manager.
    connection_manager = ConnectionManager(job_uuid,
                                           CONFIG["pg_host"],
                                           CONFIG["pg_port"],
                                           CONFIG["pg_user"],
                                           CONFIG["pg_database"],
                                           CONFIG["leave_schema"])
    with connection_manager:
        suite_result = {}
        job_params = {}
        job_params["connection_manager"] = connection_manager

        # Run check suite.
        for check in check_suite:
            # Prepare parameters.
            check_params = {}
            if check["check_ident"] in check_defaults:
                check_params.update(check_defaults[check["check_ident"]])
            if "parameters" in product_type:
                check_params.update(product_type["parameters"])
            if "parameters" in check:
                check_params.update(check["parameters"])
            check_params.update(job_params)

            # Run the check.
            func = get_check_function(check["check_ident"])
            # FIXME: currently check functions use os.path for path manipulation
            #        while upper server stack uses pathlib.
            #        it is encouraged to choose one or another.
            check_result = func(str(filepath), check_params)

            # Add result to suite results.
            suite_result[check["check_ident"]] = {}
            suite_result[check["check_ident"]]["status"] = check_result["status"]
            if "message" in check_result:
                suite_result[check["check_ident"]]["message"] = check_result["message"]
            if "params" in check_result:
                job_params.update(check_result["params"])

            # Update wps output.
            if update_result_func is not None:
                update_result_func(suite_result)

            # Abort validation if wanted.
            if check_result["status"] == "aborted":
                break


class ServiceException(Exception):
    pass


class ConnectionManager():
    func_schema_name = "qc_function"
    job_schema_name_tpl = "job_{:s}"

    def __init__(self, job_uuid, host, port, user, db_name, leave_schema):
        self.job_uuid = job_uuid
        self.host = host
        self.port = port
        self.user = user
        self.db_name = db_name
        self.leave_schema = leave_schema
        self.connection = None
        self.job_schema_name = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def _is_connected(self):
        return self.connection is not None and self.connection.closed == 0

    def _create_connection(self):
        try:
            connection = connect(host=self.host, port=self.port, user=self.user, dbname=self.db_name)
        except Exception as ex:
            msg = "Can not make db connection for the job:{:s}.".format(self.job_uuid)
            raise ServiceException(msg) from ex
        self.connection = connection
        self.connection.autocommit = True

    def _create_schema(self):
        job_uuid = self.job_uuid.lower().replace("-", "")
        job_schema_name = self.job_schema_name_tpl.format(job_uuid)
        with closing(self.connection.cursor()) as cursor:
            cursor.execute("CREATE SCHEMA {:s};".format(job_schema_name))
            self.job_schema_name = job_schema_name
            cursor.execute("SET search_path TO {:s}, {:s}, public;".format(job_schema_name, self.func_schema_name))

    def _drop_schema(self):
        with closing(self.connection.cursor()) as cursor:
            cursor.execute("DROP SCHEMA {:s} CASCADE;".format(self.job_schema_name))
            self.job_schema_name = None
            cursor.close()

    def get_dsn_schema(self):
        conn = self.get_connection()
        return (conn.dsn, self.job_schema_name)

    def get_connection(self):
        if self._is_connected():
            return self.connection
        self._create_connection()
        if self.job_schema_name is None:
            self._create_schema()
        return self.connection

    def close(self):
        if not (self.leave_schema or self.job_schema_name is None):
            if not self._is_connected():
                conn = self._create_connection()
            self._drop_schema()
        if self._is_connected():
            self.connection.close()
        self.connection = None
