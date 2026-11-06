#!/usr/bin/env python3


from contextlib import closing
from shutil import rmtree

from psycopg2 import connect
from psycopg2 import sql

from qc_tool.common import CONFIG
from qc_tool.common import JOB_OUTPUT_DIRNAME
from qc_tool.common import JOB_TMP_DIRNAME
from qc_tool.common import compose_job_dir
from qc_tool.storage.layout import runtime_paths
from qc_tool.worker.jobs import job_schema_name
from qc_tool.worker.jobs import normalize_job_uuid
from qc_tool.worker.scratch import ScratchLease


def create_connection_manager(job_uuid):
    connection_manager = ConnectionManager(job_uuid,
                                           CONFIG["pg_host"],
                                           CONFIG["pg_port"],
                                           CONFIG["pg_user"],
                                           CONFIG["pg_database"],
                                           CONFIG["leave_schema"])
    return connection_manager

def create_jobdir_manager(job_uuid):
    job_uuid = normalize_job_uuid(job_uuid)
    job_dir = compose_job_dir(job_uuid)
    paths = runtime_paths(CONFIG)
    jobdir_manager = JobdirManager(
        job_dir, CONFIG["leave_jobdir"],
        scratch_dir=paths.job_scratch_dir(job_uuid) if paths.scratch_dir is not None else None,
        job_uuid=job_uuid,
    )
    return jobdir_manager


class ConnectionException(Exception):
    pass


class ConnectionManager():
    def __init__(self, job_uuid, host, port, user, db_name, leave_schema):
        self.job_uuid = normalize_job_uuid(job_uuid)
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
            raise ConnectionException(msg) from ex
        self.connection = connection
        self.connection.autocommit = True

    def _create_job_schema(self):
        schema_name = job_schema_name(self.job_uuid)
        with closing(self.connection.cursor()) as cursor:
            cursor.execute(
                sql.SQL("CREATE SCHEMA {};").format(sql.Identifier(schema_name))
            )
            self.job_schema_name = schema_name
            cursor.execute(
                sql.SQL("SET search_path TO {}, public;").format(
                    sql.Identifier(schema_name)
                )
            )

    def _drop_job_schema(self):
        with closing(self.connection.cursor()) as cursor:
            cursor.execute(
                sql.SQL("DROP SCHEMA {} CASCADE;").format(
                    sql.Identifier(self.job_schema_name)
                )
            )
            self.job_schema_name = None

    def get_dsn_schema(self):
        conn = self.get_connection()
        return (conn.dsn, self.job_schema_name)

    def get_connection(self):
        if self._is_connected():
            return self.connection
        self._create_connection()
        if self.job_schema_name is None:
            self._create_job_schema()
        return self.connection

    def close(self):
        if not self.leave_schema and self.job_schema_name is not None:
            if not self._is_connected():
                conn = self._create_connection()
            self._drop_job_schema()
        if self._is_connected():
            self.connection.close()
        self.connection = None


class JobdirManager():
    def __init__(self, job_dir, leave_dir=False, *, scratch_dir=None, job_uuid=None):
        self.job_dir = job_dir
        self.leave_dir = leave_dir
        self.tmp_dir = None
        self.output_dir = None
        self.scratch_dir = scratch_dir
        self.job_uuid = job_uuid
        self.scratch_lease = None

    def __enter__(self):
        try:
            self.create_dirs()
        except BaseException:
            if self.scratch_lease is not None:
                self.scratch_lease.close()
            raise
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            self.remove_tmp_dir()
        finally:
            if self.scratch_lease is not None:
                self.scratch_lease.close()

    def create_dirs(self):
        output_dir = self.job_dir.joinpath(JOB_OUTPUT_DIRNAME)
        output_dir.mkdir(parents=True)
        self.output_dir = output_dir
        if self.scratch_dir is None:
            tmp_dir = self.job_dir.joinpath(JOB_TMP_DIRNAME)
            tmp_dir.mkdir(parents=True)
            self.tmp_dir = tmp_dir
        else:
            self.scratch_lease = ScratchLease(self.scratch_dir, self.job_uuid, retain=self.leave_dir)
            self.scratch_lease.__enter__()
            self.tmp_dir = self.scratch_lease.directory / JOB_TMP_DIRNAME
            self.tmp_dir.mkdir(mode=0o700)

    def remove_tmp_dir(self):
        if not self.leave_dir and self.tmp_dir is not None:
            directory = self.scratch_lease.directory if self.scratch_lease is not None else self.tmp_dir
            rmtree(str(directory))
        self.tmp_dir = None
