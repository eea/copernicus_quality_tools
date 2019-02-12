#!/usr/bin/env python3


import json
from pathlib import Path

from qc_tool.common import TEST_DATA_DIR
from qc_tool.common import compose_attachment_filepath
from qc_tool.common import compose_job_status_filepath
from qc_tool.test.helper import ProductTestCase
from qc_tool.wps.dispatch import dispatch


class Test_clc(ProductTestCase):
    def test(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb.zip")

        expected_check_statuses = {"v_unzip": "ok",
                                   "v1_clc": "ok",
                                   "v2": "ok",
                                   "reference.v3": "ok",
                                   "initial.v3": "ok",
                                   "change.v3": "ok",
                                   "v4_clc": "ok",
                                   "v_import2pg": "ok",
                                   "v5": "ok",
                                   "reference.v6": "ok",
                                   "initial.v6": "ok",
                                   "change.v6": "ok",
                                   "v8": "ok",
                                   "v10": "ok",
                                   "v11_clc_status": "ok",
                                   "v11_clc_change": "ok",
                                   "v12": "ok",
                                   "v13": "ok",
                                   "reference.v14": "ok",
                                   "initial.v14": "ok",
                                   "change.v14": "ok",
                                   "v15": "skipped"}

        job_status = dispatch(self.job_uuid,
                              "user_name",
                              filepath,
                              "clc_2012",
                              ["v5",
                               "reference.v6",
                               "initial.v6",
                               "change.v6",
                               "v8",
                               "v10",
                               "v11_clc_status",
                               "v11_clc_change",
                               "v12",
                               "v13",
                               "reference.v14",
                               "initial.v14",
                               "change.v14"])

        check_statuses = dict((check_status["check_ident"], check_status["status"])
                              for check_status in job_status["checks"])
        self.assertDictEqual(expected_check_statuses, check_statuses)


class Test_clc_status(ProductTestCase):
    def test_status_json(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb.zip")
        status_filepath = compose_job_status_filepath(self.job_uuid)
        job_status = dispatch(self.job_uuid, "user_name", filepath, "clc_2012", [])
        self.assertTrue(status_filepath.exists())
        job_status_from_file = status_filepath.read_text()
        job_status_from_file = json.loads(job_status_from_file)
        self.assertEqual(job_status, job_status_from_file,
                         "Job status returned by dispatch() must be the same as stored in status.json file.")


class Test_n2k(ProductTestCase):
    def test(self):
        self.filepath = TEST_DATA_DIR.joinpath("vector", "n2k", "n2k_example_cz_correct.zip")
        expected_check_statuses = {"v_unzip": "ok",
                                   "v1_n2k": "ok",
                                   "v2": "ok",
                                   "v3": "ok",
                                   "v4": "ok",
                                   "v_import2pg": "ok",
                                   "v5": "ok",
                                   "v6": "ok",
                                   "v8": "ok",
                                   "v10_unit": "ok",
                                   "v11_n2k": "ok",
                                   "v12": "ok",
                                   "v13": "ok",
                                   "v14": "ok",
                                   "v15": "skipped"}  # v15 is intentionally skipped.
        job_status = dispatch(self.job_uuid,
                              "user_name",
                              self.filepath,
                              "n2k",
                              ["v5", "v6", "v8", "v10_unit", "v11_n2k", "v12", "v13", "v14"])
        check_statuses = dict((check_status["check_ident"], check_status["status"])
                              for check_status in job_status["checks"])
        self.assertDictEqual(expected_check_statuses, check_statuses)


class Test_rpz(ProductTestCase):
    def test(self):
        self.filepath = TEST_DATA_DIR.joinpath("vector", "rpz", "rpz_LCLU2012_DU007T.zip")
        expected_check_statuses = {"v_unzip": "ok",
                                   "v1_rpz": "ok",
                                   "v2": "ok",
                                   "v3": "ok",
                                   "v4": "ok",
                                   "v_import2pg": "ok",
                                   "v5": "ok",
                                   "v6": "ok",
                                   "v8": "ok",
                                   "v10_unit": "ok",
                                   "v11_rpz": "ok",
                                   "v12": "ok",
                                   "v13": "ok",
                                   "v14_rpz": "ok",
                                   "v15": "skipped"}  # v15 is intentionally skipped.
        job_status = dispatch(self.job_uuid,
                              "user_name",
                              self.filepath,
                              "rpz",
                              ["v5", "v6", "v8", "v10_unit", "v11_rpz", "v12", "v13", "v14_rpz"])
        check_statuses = dict((check_status["check_ident"], check_status["status"])
                              for check_status in job_status["checks"])
        self.assertDictEqual(expected_check_statuses, check_statuses)


class Test_ua_shp(ProductTestCase):
    def test(self):
        self.filepath = TEST_DATA_DIR.joinpath("vector", "ua_shp", "EE003L0_NARVA.shp.zip")
        expected_check_statuses = {"v_unzip": "ok",
                                   "v1_ua_shp": "ok",
                                   "v2": "ok",
                                   "reference.v3": "ok",
                                   "v4": "ok",
                                   "v_import2pg": "ok",
                                   "v5": "ok",
                                   "v6": "ok",
                                   "v8": "ok",
                                   "v10": "ok",
                                   "v11_ua_status": "ok",
                                   "v12_ua": "ok",
                                   "v13": "ok",
                                   "v14": "ok",
                                   "v15": "skipped"  # v15 is intentionally skipped.
                                   }
        job_status = dispatch(self.job_uuid,
                              "user_name",
                              self.filepath,
                              "ua_2012_shp_wo_revised",
                              ["v5", "v6", "v8", "v10", "v11_ua_status", "v12_ua", "v13", "v14"])
        check_statuses = dict((check_status["check_ident"], check_status["status"])
                              for check_status in job_status["checks"])
        self.assertDictEqual(expected_check_statuses, check_statuses)


class Test_ua_gdb(ProductTestCase):
    def test(self):
        self.maxDiff = None
        filepath = TEST_DATA_DIR.joinpath("vector", "ua_gdb", "DK001L2_KOBENHAVN_clip.zip")
        expected_check_statuses = {"v_unzip": "ok",
                                   "v1_ua_gdb": "ok",
                                   "v2": "ok",
                                   "reference.v3": "ok",
                                   "revised.v3": "ok",
                                   "combined_change.v3": "ok",
                                   "v4": "ok",
                                   "v_import2pg": "ok",
                                   "v5": "ok",
                                   "reference.v6": "ok",
                                   "revised.v6": "ok",
                                   "combined_change.v6": "ok",
                                   "v8": "ok",
                                   "v10": "ok",
                                   "reference.v11_ua_status": "ok",
                                   "revised.v11_ua_status": "ok",
                                   "change.v11_ua_change": "ok",
                                   "reference.v12_ua": "ok",
                                   "revised.v12_ua": "ok",
                                   "v13": "ok",
                                   "reference.v14": "ok",
                                   "revised.v14": "ok",
                                   "combined_change.v14": "ok"}
        job_status = dispatch(self.job_uuid,
                              "user_name",
                              filepath,
                              "ua_2012_gdb",
                              ["v5",
                               "reference.v6",
                               "revised.v6",
                               "combined_change.v6",
                               "v8",
                               "v10",
                               "reference.v11_ua_status",
                               "revised.v11_ua_status",
                               "change.v11_ua_change",
                               "reference.v12_ua",
                               "revised.v12_ua",
                               "v13",
                               "reference.v14",
                               "revised.v14",
                               "combined_change.v14"])
        check_statuses = dict((check_status["check_ident"], check_status["status"])
                              for check_status in job_status["checks"])
        self.assertDictEqual(expected_check_statuses, check_statuses)
