#!/usr/bin/env python3


from contextlib import closing
from contextlib import ExitStack
from unittest import TestCase
from uuid import uuid4

from qc_tool.common import DB_FUNCTION_DIR
from qc_tool.common import DB_FUNCTION_SCHEMA_NAME
from qc_tool.wps.dispatch import CheckStatus
from qc_tool.wps.manager import create_connection_manager
from qc_tool.wps.manager import create_jobdir_manager


class ProductTestCase(TestCase):
    def setUp(self):
        super().setUp()
        with create_connection_manager(str(uuid4())) as connection_manager:
            cursor = connection_manager.get_connection().cursor()
            sql = "DROP SCHEMA {:s} CASCADE;".format(DB_FUNCTION_SCHEMA_NAME)
            cursor.execute(sql)
            sql = "CREATE SCHEMA {:s};".format(DB_FUNCTION_SCHEMA_NAME)
            cursor.execute(sql)
            sql = "SET search_path TO {:s};".format(DB_FUNCTION_SCHEMA_NAME)
            cursor.execute(sql)
            for filepath in sorted(DB_FUNCTION_DIR.glob("*.sql")):
                    sql_script = filepath.read_text()
                    cursor.execute(sql_script)


class RasterCheckTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.status_class = CheckStatus
        self.job_uuid = str(uuid4())
        with ExitStack() as stack:
            self.jobdir_manager = stack.enter_context(create_jobdir_manager(self.job_uuid))
            self.addCleanup(stack.pop_all().close)


class VectorCheckTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.status_class = CheckStatus
        self.job_uuid = str(uuid4())
        self.params = {}
        with ExitStack() as stack:
             self.params["connection_manager"] = stack.enter_context(create_connection_manager(self.job_uuid))
             self.params["jobdir_manager"] = stack.enter_context(create_jobdir_manager(self.job_uuid))
             self.addCleanup(stack.pop_all().close)

        # Reload database functions every time job schema is created.
        _connection_manager = self.params["connection_manager"]
        _create_schema = _connection_manager._create_schema
        def _create_schema_with_reload():
            _create_schema()
            with closing(_connection_manager.connection.cursor()) as cursor:
                sql = "SET search_path TO {:s}, public;".format(_connection_manager.job_schema_name)
                cursor.execute(sql)
                for filepath in sorted(DB_FUNCTION_DIR.glob("*.sql")):
                    sql_script = filepath.read_text()
                    cursor.execute(sql_script)
        _connection_manager._create_schema = _create_schema_with_reload
