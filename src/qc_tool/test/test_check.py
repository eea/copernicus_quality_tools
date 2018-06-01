#!/usr/bin/env python3


from unittest import TestCase
from uuid import uuid4

from qc_tool.common import TEST_DATA_DIR
from qc_tool.wps.manager import create_connection_manager


class TestImport2pg(TestCase):
    valid_geodatabase = "clc2012_mt.gdb"

    def setUp(self):
        self.job_uuid = str(uuid4())
        self.connection_manager = create_connection_manager(self.job_uuid)


    def test_import2pg_pass(self):
        from qc_tool.wps.vector_check.import2pg import run_check
        filepath = str(TEST_DATA_DIR.joinpath(self.valid_geodatabase))
        params = {"country_codes": "(CZ|MT)",
                  "layer_regex": "^countrycode/clc[0-9]{2}_countrycode$",
                  "connection_manager": self.connection_manager}
        result = run_check(filepath, params)
        self.assertEqual("ok", result["status"])


    def test_import2pg_table_created(self):
        from qc_tool.wps.vector_check.import2pg import run_check
        filepath = str(TEST_DATA_DIR.joinpath(self.valid_geodatabase))
        params = {"country_codes": "(CZ|MT)",
                  "layer_regex": "^countrycode/clc[0-9]{2}_countrycode$",
                  "connection_manager": self.connection_manager}
        run_check(filepath, params)

        conn = self.connection_manager.get_connection()
        cur = conn.cursor()
        layer = "clc12_mt"
        cur.execute("""SELECT id FROM {:s}""".format(layer))
        num_rows = cur.rowcount
        self.assertGreater(num_rows, 0, "imported table does not have any rows.")

    def tearDown(self):
        self.connection_manager.close()


class TestV11_DataNotImported(TestCase):
    def setUp(self):
        self.connection_manager = create_connection_manager(str(uuid4()))

    def test_missing_table_should_cause_fail(self):
        from qc_tool.wps.vector_check.v11 import run_check
        filepath = TEST_DATA_DIR.joinpath("clc2012_mt.gdb")
        params = {"area_ha": 25,
                  "border_exception": True,
                  "connection_manager": self.connection_manager}
        result = run_check(filepath, params)
        if "message" in result:
            print(result["message"])
        self.assertEqual("failed", result["status"], "check result should be FAILED when table is not imported.")

    def tearDown(self):
        self.connection_manager.close()


class TestV11(TestCase):
    def setUp(self):
        self.job_uuid = str(uuid4())
        self.connection_manager = create_connection_manager(self.job_uuid)
        from qc_tool.wps.vector_check.import2pg import run_check
        filepath = str(TEST_DATA_DIR.joinpath("clc2012_mt.gdb"))
        params = {"country_codes": "(CZ|MT)",
                  "layer_regex": "^countrycode/clc[0-9]{2}_countrycode$",
                  "connection_manager": self.connection_manager}
        run_check(filepath, params)

    def tearDown(self):
        self.connection_manager.close()

    def test_v11(self):
        from qc_tool.wps.vector_check.v11 import run_check
        filepath = TEST_DATA_DIR.joinpath("clc2012_mt.gdb")
        params = {"area_ha": 25,
                  "border_exception": True,
                  "connection_manager": self.connection_manager}
        run_check(filepath, params)

    def test_v11_small_mmu_should_pass(self):
        from qc_tool.wps.vector_check.v11 import run_check
        filepath = TEST_DATA_DIR.joinpath("clc2012_mt.gdb")
        params = {"area_ha": 25,
                  "border_exception": True,
                  "connection_manager": self.connection_manager}
        result = run_check(filepath, params)
        if "message" in result:
            print(result["message"])
        self.assertEqual("ok", result["status"], "check result should be ok for MMU=25ha.")

    def test_v11_big_mmu_should_fail(self):
        from qc_tool.wps.vector_check.v11 import run_check
        filepath = TEST_DATA_DIR.joinpath("clc2012_mt.gdb")
        params = {"area_ha": 250,
                  "border_exception": True,
                  "connection_manager": self.connection_manager}
        result = run_check(filepath, params)
        if "message" in result:
            print(result["message"])
        self.assertEqual("failed", result["status"], "check result should be 'failed' for MMU=250ha.")

    def test_v11_border_table_created(self):
        """
        a _polyline_border table should be created in the job's schema
        :return:
        """
        from qc_tool.wps.vector_check.v11 import run_check
        filepath = TEST_DATA_DIR.joinpath("clc2012_mt.gdb")
        layer = "clc12_mt"
        params = {"area_ha": 200,
                  "border_exception": True,
                  "connection_manager": self.connection_manager}
        run_check(filepath, params)

        conn = params["connection_manager"].get_connection()
        cur = conn.cursor()

        expected_table = "{:s}_polyline_border".format(layer)
        cur.execute("SELECT table_name FROM information_schema.tables where table_name='{:s}'".format(expected_table))
        row = cur.fetchone()
        self.assertIsNotNone(row, "v1 should create a polyline_border table in the database.")


    def test_v11_border_table_not_in_public(self):
        """
        a _polyline_border table should be created in the job's schema
        :return:
        """
        from qc_tool.wps.vector_check.v11 import run_check
        filepath = TEST_DATA_DIR.joinpath("clc2012_mt.gdb")
        layer = "clc12_mt"
        params = {"area_ha": 200,
                  "border_exception": True,
                  "connection_manager": self.connection_manager}
        result = run_check(filepath, params)

        # get connection and cursor
        conn = params["connection_manager"].get_connection()
        cur = conn.cursor()

        border_table = "{:s}_polyline_border".format(layer)
        cur.execute("SELECT table_schema, table_name FROM information_schema.tables \
                     where table_schema='public' AND table_name = '{:s}'".format(border_table))
        row = cur.fetchone()
        self.assertIsNone(row, "border table {:s} should not be in the public schema.".format(border_table))


    def test_v11_border_table_in_job_schema(self):
        """
        a _polyline_border table should be created in the job's schema
        :return:
        """
        from qc_tool.wps.vector_check.v11 import run_check
        filepath = TEST_DATA_DIR.joinpath("clc2012_mt.gdb")
        layer = "clc12_mt"
        params = {"area_ha": 200,
                  "border_exception": True,
                  "connection_manager": self.connection_manager}
        result = run_check(filepath, params)

        # get connection and cursor
        conn = params["connection_manager"].get_connection()
        cur = conn.cursor()

        border_table = "{:s}_polyline_border".format(layer)
        expected_schema = self.connection_manager.get_dsn_schema()[1]
        cur.execute("SELECT table_schema, table_name FROM information_schema.tables \
                     where table_schema='{:s}' AND table_name='{:s}'".format(expected_schema, border_table))
        row = cur.fetchone()
        self.assertIsNotNone(row, "polyline_border table should be created in the current job schema.")
