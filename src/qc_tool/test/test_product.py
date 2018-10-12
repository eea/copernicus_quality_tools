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
        from qc_tool.common import CONFIG
        CONFIG["boundary_dir"] = TEST_DATA_DIR.joinpath("boundary")

    def test(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb.zip")
        job_status = dispatch(str(uuid4()),
                              "user_name",
                              filepath,
                              "clc",
                              ["v5",
                               "status.v6",
                               "change.v6",
                               "v8",
                               "status.v11",
                               "change.v11",
                               "v13",
                               "status.v14",
                               "change.v14"])

        statuses_ok = [check for check in job_status["checks"] if check["status"] == "ok"]
        checks_not_ok = [check["check_ident"] for check in job_status["checks"] if check["status"] != "ok"]

        self.assertEqual(len(statuses_ok), len(job_status["checks"]),
                         "Checks {:s} do not have status ok.".format(",".join(checks_not_ok)))


class Test_clc_status(TestCase):
    def setUp(self):
        super().setUp()
        load_all_check_functions()

    def test_status_json(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb.zip")
        job_uuid = uuid4().hex
        status_filepath = Path("/mnt/qc_tool_volume/work/").joinpath("job_{:s}".format(job_uuid), "status.json")
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
        # FIXME:
        # Narva test zip should be removed while it fails in some checks.
        # The new test zip should pass all checks with ok status.
        self.filepath = TEST_DATA_DIR.joinpath("vector", "ua_shp", "EE003L0_NARVA.shp.zip")

    def test_run(self):
        expected_check_statuses = {"v_unzip": "ok",
                                   "v1_ua": "ok",
                                   "boundary.v2": "ok",
                                   "boundary.v3": "ok",
                                   "boundary.v4": "ok",
                                   "boundary.v_import2pg": "ok",
                                   "reference.v2": "ok",
                                   "reference.v3": "ok",
                                   "reference.v4": "ok",
                                   "reference.v_import2pg": "ok",
                                   "reference.v5": "ok",
                                   "reference.v6": "ok",
                                   "reference.v8": "ok",
                                   "reference.v11_ua": "failed", #FIXME: the status should be ok in v11_ua.
                                   "reference.v13": "ok",
                                   "reference.v14": "ok"}
        job_status = dispatch(str(uuid4()),
                              "user_name",
                              self.filepath,
                              "ua",
                              ["reference.v5",
                               "reference.v6",
                               "reference.v8",
                               "reference.v11_ua",
                               "reference.v13",
                               "reference.v14"])
        check_statuses = dict((check_status["check_ident"], check_status["status"])
                              for check_status in job_status["checks"])
        self.assertDictEqual(expected_check_statuses, check_statuses)


class Test_ua_gdb(ProductTestCase):
    def setUp(self):
        super().setUp()
        load_all_check_functions()
        # FIXME:
        # Klagenfurt test zip should be removed while it fails in some checks.
        # The new test zip should pass all checks with ok status.
        self.filepath = TEST_DATA_DIR.joinpath("vector", "ua_gdb", "AT006L1_KLAGENFURT.zip")

    def test_run_ok(self):
        expected_check_statuses = {"v_unzip": "ok",
                                   "v1_ua": "ok",
                                   "boundary.v2": "ok",
                                   "boundary.v3": "ok",
                                   "boundary.v4": "ok",
                                   "boundary.v_import2pg": "ok",
                                   "reference.v2": "ok",
                                   "reference.v3": "ok",
                                   "reference.v4": "ok",
                                   "reference.v_import2pg": "ok",
                                   "reference.v5": "ok",
                                   "reference.v6": "ok",
                                   "reference.v8": "ok",
                                   "reference.v11_ua": "failed",
                                   "reference.v13": "failed",
                                   "reference.v14": "ok"}
        job_status = dispatch(str(uuid4()),
                              "user_name",
                              self.filepath,
                              "ua",
                              ["reference.v5", "reference.v6", "reference.v8", "reference.v11_ua", "reference.v13", "reference.v14"])
        check_statuses = dict((check_status["check_ident"], check_status["status"])
                              for check_status in job_status["checks"])
        self.assertDictEqual(expected_check_statuses, check_statuses)

    def test_kobenhavn_ok(self):
        self.maxDiff = None
        kobenhavn_filepath = TEST_DATA_DIR.joinpath("vector", "ua_gdb", "DK001L2_KOBENHAVN_clip.zip")
        expected_check_statuses = {"v_unzip": "ok",
                                   "v1_ua": "ok",
                                   "boundary.v2": "ok",
                                   "boundary.v3": "ok",
                                   "boundary.v4": "ok",
                                   "boundary.v_import2pg": "ok",
                                   "reference.v2": "ok",
                                   "reference.v3": "ok",
                                   "reference.v4": "ok",
                                   "reference.v_import2pg": "ok",
                                   "reference.v5": "ok",
                                   "reference.v6": "ok",
                                   "reference.v8": "ok",
                                   "reference.v11_ua": "ok",
                                   "reference.v13": "ok",
                                   "reference.v14": "ok",
                                   "combined.v2": "ok",
                                   "combined.v3": "ok",
                                   "combined.v4": "ok",
                                   "combined.v_import2pg": "ok",
                                   "combined.v5": "ok",
                                   "combined.v6": "ok",
                                   "combined.v8": "ok",
                                   "combined.v11_ua": "ok",
                                   "combined.v13": "ok",
                                   "combined.v14": "ok",
                                   "revised.v2": "ok",
                                   "revised.v3": "ok",
                                   "revised.v4": "ok",
                                   "revised.v_import2pg": "ok",
                                   "revised.v6": "ok",
                                   "revised.v8": "ok",
                                   "revised.v11_ua": "ok",
                                   "revised.v13": "ok",
                                   "revised.v14": "ok",
                                   "change.v2": "ok",
                                   "change.v3": "ok",
                                   "change.v4": "ok",
                                   "change.v_import2pg": "ok",
                                   "change.v5": "ok",
                                   "change.v6": "ok",
                                   "change.v8": "ok",
                                   "change.v11_ua": "ok",
                                   "change.v13": "ok",
                                   "change.v14": "ok"}
        job_status = dispatch(str(uuid4()),
                              "user_name",
                              kobenhavn_filepath,
                              "ua_with_change",
                              ["reference.v5",
                               "reference.v6",
                               "reference.v8",
                               "reference.v11_ua",
                               "reference.v13",
                               "reference.v14",
                               "combined.v5",
                               "combined.v6",
                               "combined.v8",
                               "combined.v11_ua",
                               "combined.v13",
                               "combined.v14",
                               "revised.v6",
                               "revised.v8",
                               "revised.v11_ua",
                               "revised.v13",
                               "revised.v14",
                               "change.v5",
                               "change.v6",
                               "change.v8",
                               "change.v11_ua",
                               "change.v13",
                               "change.v14"])
        check_statuses = dict((check_status["check_ident"], check_status["status"])
                              for check_status in job_status["checks"])
        self.assertDictEqual(expected_check_statuses, check_statuses)
