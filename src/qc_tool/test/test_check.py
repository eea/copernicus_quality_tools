#!/usr/bin/env python3


from unittest import TestCase
from uuid import uuid4

from qc_tool.common import CONFIG
from qc_tool.common import TEST_DATA_DIR


def get_connection_manager():
    from qc_tool.wps.dispatch import ConnectionManager
    connection_manager = ConnectionManager(str(uuid4()),
                                           CONFIG["pg_host"],
                                           CONFIG["pg_port"],
                                           CONFIG["pg_user"],
                                           CONFIG["pg_database"],
                                           CONFIG["leave_schema"])
    return connection_manager

class TestV11(TestCase):

    def setUp(self):
        self.connection_manager = get_connection_manager()

    def tearDown(self):
        self.connection_manager.close()

    def test_v11(self):
        from qc_tool.wps.vector_check.v11 import run_check
        filepath = TEST_DATA_DIR.joinpath("clc2012_mt.gdb")
        params = {"area_ha":200, "border_exception":True,
                  "connection_manager":self.connection_manager}
        result = run_check(filepath, params)
        self.assertEqual("ok", result["status"])
