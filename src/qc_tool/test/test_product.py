#!/usr/bin/env python3


from unittest import TestCase
from uuid import uuid4

from qc_tool.common import TEST_DATA_DIR
from qc_tool.wps.dispatch import dispatch
from qc_tool.wps.registry import load_all_check_functions


class Test_fty_YYYY_020m(TestCase):
    def setUp(self):
        load_all_check_functions()

    def test_run(self):
        filepath = TEST_DATA_DIR.joinpath("fty_2015_020m_si_03035_d04_test.tif")
        job_status = dispatch(str(uuid4()), filepath, "fty_YYYY_020m", [])
        self.assertEqual("fty_YYYY_020m.r1", job_status["checks"][0]["check_ident"])
        self.assertEqual("ok", job_status["checks"][0]["status"],
                         "Slovenia test file should pass check for the product fty_YYYY_020m.")

    def test_bad_extension(self):
        filepath = TEST_DATA_DIR.joinpath("clc2012_mt.gdb")
        job_status = dispatch(str(uuid4()), filepath, "fty_YYYY_020m", [])
        self.assertEqual("fty_YYYY_020m.r1", job_status["checks"][0]["check_ident"])
        self.assertEqual("aborted", job_status["checks"][0]["status"],
                         "r1 should return aborted with bad extension.")


class Test_clc(TestCase):
    def setUp(self):
        load_all_check_functions()

    def test_run(self):
        filepath = TEST_DATA_DIR.joinpath("clc2012_mt.gdb")
        job_status = dispatch(str(uuid4()), filepath, "clc", [])


class Test_clc_status(TestCase):
    def setUp(self):
        load_all_check_functions()

    def test_run(self):
        filepath = TEST_DATA_DIR.joinpath("clc2012_mt.gdb")
        job_status = dispatch(str(uuid4()), filepath, "clc.status", [])
        self.assertEqual("clc.status.v1", job_status["checks"][0]["check_ident"])
        self.assertEqual("ok", job_status["checks"][0]["status"],
                         "Malta should pass the checks for the product clc.status.")


class Test_update_status(TestCase):
    def setUp(self):
        load_all_check_functions()

    def test_run(self):
        def my_update(check_ident, percent_done):
            pass
        filepath = TEST_DATA_DIR.joinpath("clc2012_mt.gdb")
        dispatch(str(uuid4()),
                 filepath,
                 "clc.status",
                 ["clc.status.v3", "clc.status.v4", "clc.status.v5", "clc.status.v6", "clc.status.v8", "clc.status.v11"],
                 update_status_func=my_update)
