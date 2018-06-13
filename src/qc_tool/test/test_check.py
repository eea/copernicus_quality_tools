#!/usr/bin/env python3
from pathlib import Path
from subprocess import run

from unittest import TestCase
from uuid import uuid4

from qc_tool.common import TEST_DATA_DIR
from qc_tool.wps.manager import create_connection_manager
from qc_tool.wps.manager import create_jobdir_manager


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
        self.assertLess(0, num_rows, "imported table should have at least one row.")

    def test_import2pg_functions_created(self):
        from qc_tool.wps.vector_check.import2pg import run_check
        filepath = str(TEST_DATA_DIR.joinpath(self.valid_geodatabase))
        params = {"country_codes": "(CZ|MT)",
                  "layer_regex": "^countrycode/clc[0-9]{2}_countrycode$",
                  "connection_manager": self.connection_manager}
        run_check(filepath, params)

        job_schema = self.connection_manager.get_dsn_schema()[1]
        expected_function_names = ["__v11_mmu_status",
                                   "__v11_mmu_polyline_border",
                                   "__v5_uniqueid",
                                   "__v6_validcodes",
                                   "__v8_multipartpolyg",
                                   "__v11_mmu_change_clc"]
        conn = self.connection_manager.get_connection()
        cur = conn.cursor()
        cur.execute("""SELECT routine_name FROM information_schema.routines \
                       WHERE routine_type='FUNCTION' AND routine_schema='{:s}'""".format(job_schema))

        actual_function_names = [row[0] for row in cur.fetchall()]

        for expected_name in expected_function_names:
            self.assertIn(expected_name, actual_function_names,
                          "a function {:s} should be created in schema {:s}".format(expected_name, job_schema))

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

class TestR2(TestCase):
    def test_r2(self):
        from qc_tool.wps.raster_check.r2 import run_check
        filepath = str(TEST_DATA_DIR.joinpath("fty_2015_020m_si_03035_d04_test.tif"))
        params = {"country_codes": "(AL|AT|BA|BE|BG|CH|CY|CZ|DE|DK|EE|ES|EU|FI|FR|GR|HR|HU|IE|IS|IT|XK|LI|LT|LU|LV|ME|MK|MT|NL|NO|PL|PT|RO|SE|SI|SK|TR|UK|UK_NI|ES_CN|PT_RAA|PT_RAM|UK_GE|UK_JE|FR_GLP|FR_GUF|FR_MTQ|FR_MYT|FR_REU|PT_RAA_CEG|PT_RAA_WEG)",
                  "extensions": [".tif", ".tfw", ".clr", ".xml", ".tif.vat.dbf"],
                  "file_name_regex": "^fty_[0-9]{4}_020m_countrycode_[0-9]{5}.*.tif$"}
        result = run_check(filepath, params)
        if "message" in result:
            print(result["message"])
        self.assertEqual("ok", result["status"], "raster check r2 should pass")

class TestR11(TestCase):
    def setUp(self):
        self.jobdir_manager = create_jobdir_manager(str(uuid4()))
        self.jobdir_manager.create_dir()

    def test_r11_jobdir(self):
        self.assertIsNotNone(self.jobdir_manager.job_dir, "job_dir should be a valid directory")

    def test_r11_jobdir_exists(self):
        self.assertIsNotNone(self.jobdir_manager.job_dir.exists(), "job_dir directory must exist.")

    def test_r11(self):
        from qc_tool.wps.raster_check.r11 import run_check
        filepath = str(TEST_DATA_DIR.joinpath("fty_2015_020m_si_03035_d04_test.tif"))
        params = {"area_ha": 5, "job_dir": str(self.jobdir_manager.job_dir)}
        result = run_check(filepath, params)
        print(result)
        self.assertEqual("failed", result["status"])
        self.assertNotIn("GRASS GIS error", result["message"])

    def tearDown(self):
        self.jobdir_manager.remove_dir()

class TestR15(TestCase):
    def test_r15(self):
        from qc_tool.wps.raster_check.r15 import run_check
        filepath = str(TEST_DATA_DIR.joinpath("fty_2015_020m_si_03035_d04_test.tif"))
        print(type(filepath))
        params = {"colours": {
          "0":[240, 240, 240],
          "1":[70, 158, 74],
          "2":[28, 92, 36],
          "254":[153, 153, 153],
          "255":[0, 0, 1]
        }}
        result = run_check(filepath, params)


class TestV8(TestCase):
    def setUp(self):
        self.job_uuid = str(uuid4())
        self.connection_manager = create_connection_manager(self.job_uuid)
        from qc_tool.wps.vector_check.import2pg import run_check
        filepath = str(TEST_DATA_DIR.joinpath("clc2012_mt.gdb"))
        params = {"country_codes": "(CZ|MT)",
                  "layer_regex": "^countrycode/clc[0-9]{2}_countrycode$",
                  "connection_manager": self.connection_manager}
        run_check(filepath, params)

    def test_v8(self):
        from qc_tool.wps.vector_check.v8 import run_check
        filepath = TEST_DATA_DIR.joinpath("clc2012_mt.gdb")
        params = {"connection_manager": self.connection_manager}
        run_check(filepath, params)

    def test_v8_NoMultipart_ok(self):
        from qc_tool.wps.vector_check.v8 import run_check
        filepath = TEST_DATA_DIR.joinpath("clc2012_mt.gdb")
        params = {"connection_manager": self.connection_manager}
        result = run_check(filepath, params)
        if "message" in result:
            print(result["message"])
        self.assertEqual("ok", result["status"], "check result should be ok for Malta")


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
        params = {"area_ha": 200, "border_exception": True, "connection_manager": self.connection_manager}
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
        params = {"area_ha": 200, "border_exception": True, "connection_manager": self.connection_manager}
        run_check(filepath, params)

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
        params = {"area_ha": 200, "border_exception": True, "connection_manager": self.connection_manager}
        run_check(filepath, params)

        conn = params["connection_manager"].get_connection()
        cur = conn.cursor()
        border_table = "{:s}_polyline_border".format(layer)
        expected_schema = self.connection_manager.get_dsn_schema()[1]
        cur.execute("SELECT table_schema, table_name FROM information_schema.tables \
                     where table_schema='{:s}' AND table_name='{:s}'".format(expected_schema, border_table))
        row = cur.fetchone()
        self.assertIsNotNone(row, "polyline_border table should be created in the current job schema.")

    def test_v11_lessmmu_error_table_in_job_schema(self):
        """
        a *_lessmmu_error table should be created in the job's schema
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
        expected_table = "{:s}_lessmmu_error".format(layer)
        expected_schema = self.connection_manager.get_dsn_schema()[1]
        cur.execute("SELECT table_schema, table_name FROM information_schema.tables \
                     where table_schema='{:s}' AND table_name='{:s}'".format(expected_schema, expected_table))
        row = cur.fetchone()
        self.assertIsNotNone(row, "lessmmu_error table should be created in the current job schema.")

    def test_v11_lessmmu_except_table_in_job_schema(self):
        """
        a *_lessmmu_except table should be created in the job's schema
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
        expected_table = "{:s}_lessmmu_except".format(layer)
        expected_schema = self.connection_manager.get_dsn_schema()[1]
        cur.execute("SELECT table_schema, table_name FROM information_schema.tables \
                     where table_schema='{:s}' AND table_name='{:s}'".format(expected_schema, expected_table))
        row = cur.fetchone()
        self.assertIsNotNone(row, "lessmmu_except table should be created in the current job schema.")

