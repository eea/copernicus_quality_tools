#!/usr/bin/env python3


import json
from pathlib import Path
from unittest import TestCase
from uuid import uuid4

from qc_tool.common import TEST_DATA_DIR
from qc_tool.test.helper import ProductTestCase
from qc_tool.wps.dispatch import dispatch
from qc_tool.wps.registry import load_all_check_functions


class Test_fty_YYYY_020m(TestCase):
    def setUp(self):
        super().setUp()
        load_all_check_functions()

    def test_run(self):
        filepath = TEST_DATA_DIR.joinpath("raster", "fty", "fty_2015_020m_si_03035_d04_test.tif.zip")
        job_status = dispatch(str(uuid4()), "user_name", filepath, "fty_YYYY_020m", ["r2", "r3", "r4", "r5"])
        self.assertEqual("r1", job_status["checks"][1]["check_ident"])
        self.assertEqual("ok", job_status["checks"][1]["status"],
                         "Slovenia test file should pass check for the product fty_YYYY_020m.")

    def test_bad_extension(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb.zip")
        job_status = dispatch(str(uuid4()), "user_name", filepath, "fty_YYYY_020m", [])
        self.assertEqual("r_unzip", job_status["checks"][0]["check_ident"])
        self.assertEqual("aborted", job_status["checks"][0]["status"])


class Test_clc(TestCase):
    def setUp(self):
        super().setUp()
        load_all_check_functions()

    def test_malta(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb.zip")
        job_status = dispatch(str(uuid4()), "user_name", filepath, "clc", [])
        self.assertEqual("change.v2", job_status["checks"][2]["check_ident"])
        self.assertEqual("ok", job_status["checks"][2]["status"],
                         "Malta should pass the checks for the product clc.status.")


class Test_clc_status(TestCase):
    def setUp(self):
        super().setUp()
        load_all_check_functions()

    def test_status_json(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb.zip")
        job_uuid = uuid4().hex
        status_filepath = Path("/mnt/qc_tool_volume/work/").joinpath("job_{:s}".format(job_uuid), "status.json")
        print(status_filepath)
        job_status = dispatch(job_uuid, "user_name", filepath, "clc", [])
        self.assertTrue(status_filepath.exists())
        job_status_from_file = status_filepath.read_text()
        job_status_from_file = json.loads(job_status_from_file)
        self.assertEqual(job_status, job_status_from_file,
                         "Job status returned by dispatch() must be the same as stored in status.json file.")


class Test_ua_shp(ProductTestCase):
    def setUp(self):
        super().setUp()
        load_all_check_functions()

    def test_run(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "ua_shp", "EE003L0_NARVA.shp.zip")
        job_status = dispatch(str(uuid4()),
                              "user_name",
                              filepath,
                              "ua",
                              ["status.v3", "status.v4", "status.v5", "status.v6", "status.v8", "status.v11_ua",
                               "status.v13", "status.v14"])
        print(job_status["checks"])


class Test_ua_gdb(ProductTestCase):
    def setUp(self):
        super().setUp()
        load_all_check_functions()

    def test_run(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "ua_gdb", "SK007L1_TRNAVA.gdb.zip")
        job_status = dispatch(str(uuid4()),
                              "user_name",
                              filepath,
                              "ua_with_change",
                              ["change.v3", "change.v4", "change.v5", "change.v6",
                               "change.v8", "change.v11_ua", "change.v13", "change.v14"])
        print(job_status["checks"])


class Test_update_status(ProductTestCase):
    def setUp(self):
        super().setUp()
        load_all_check_functions()

    def test_run(self):
        def my_update(check_ident, percent_done):
            pass
        filepath = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb.zip")
        dispatch(str(uuid4()),
                 "user_name",
                 filepath,
                 "clc",
                 ["status.v3", "status.v4", "status.v5", "status.v6", "status.v8", "status.v11", "status.v13", "status.v14",
                  "change.v3", "change.v4", "change.v5", "change.v6", "change.v8", "change.v11", "change.v13", "change.v14"],
                 update_status_func=my_update)
