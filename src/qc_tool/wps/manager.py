#!/usr/bin/env python3


from contextlib import closing
from shutil import rmtree

from pathlib import Path, PurePath
from psycopg2 import connect

from qc_tool.common import CONFIG
from qc_tool.common import DB_FUNCTION_SCHEMA_NAME
from qc_tool.common import WORK_DIR


def create_connection_manager(job_uuid):
    connection_manager = ConnectionManager(job_uuid,
                                           CONFIG["pg_host"],
                                           CONFIG["pg_port"],
                                           CONFIG["pg_user"],
                                           CONFIG["pg_database"],
                                           CONFIG["leave_schema"])
    return connection_manager

def create_jobdir_manager(job_uuid):
    jobdir_manager = JobdirManager(job_uuid,
                                   WORK_DIR,
                                   CONFIG["jobdir_exist_ok"],
                                   CONFIG["leave_jobdir"])
    return jobdir_manager


class ConnectionException(Exception):
    pass


class ConnectionManager():
    func_schema_name = DB_FUNCTION_SCHEMA_NAME
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
            raise ConnectionException(msg) from ex
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
        if not self.leave_schema and self.job_schema_name is not None:
            if not self._is_connected():
                conn = self._create_connection()
            self._drop_schema()
        if self._is_connected():
            self.connection.close()
        self.connection = None


class JobdirManager():
    job_subdir_tpl = "job_{:s}"

    def __init__(self, job_uuid, work_dir, exist_ok=False, leave_dir=False):
        self.job_uuid = job_uuid
        self.work_dir = work_dir
        self.exist_ok = exist_ok
        self.leave_dir = leave_dir
        self.job_dir = None

    def __enter__(self):
        self.create_dir()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.remove_dir()

    def create_dir(self):
        job_uuid = self.job_uuid.lower().replace("-", "")
        job_dir = self.work_dir.joinpath(self.job_subdir_tpl.format(job_uuid))
        job_dir.mkdir(parents=True, exist_ok=self.exist_ok)
        self.job_dir = job_dir

    def remove_dir(self):
        if not self.leave_dir and self.job_dir is not None:
            rmtree(str(self.job_dir))
        self.job_dir = None
