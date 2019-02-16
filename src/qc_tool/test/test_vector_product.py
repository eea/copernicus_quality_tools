#!/usr/bin/env python3


import json
from pathlib import Path

from qc_tool.common import TEST_DATA_DIR
from qc_tool.test.helper import ProductTestCase
from qc_tool.wps.dispatch import dispatch


class Test_clc(ProductTestCase):
    def test(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb.zip")

        expected_step_statuses = {"v_unzip": "ok",
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
                                  "v9": "ok",
                                  "v10": "ok",
                                  "v11_clc_status": "ok",
                                  "v11_clc_change": "ok",
                                  "v12": "ok",
                                  "v13": "ok",
                                  "reference.v14": "ok",
                                  "initial.v14": "ok",
                                  "change.v14": "ok",
                                  "v15": "ok"}
        job_result = dispatch(self.job_uuid, "user_name", filepath, "clc_2012")
        step_statuses = dict((step_status["check_ident"], step_status["status"])
                              for step_status in job_result["steps"])
        self.assertDictEqual(expected_step_statuses, step_statuses)


class Test_clc_status(ProductTestCase):
    def test_status_json(self):
        from qc_tool.common import load_job_result
        filepath = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb.zip")
        job_result = dispatch(self.job_uuid, "user_name", filepath, "clc_2012", [])
        job_result_from_file = load_job_result(self.job_uuid)
        self.assertEqual(job_result, job_result_from_file,
                         "Job result returned by dispatch() must be the same as job result stored in json file.")


class Test_n2k(ProductTestCase):
    def test(self):
        self.filepath = TEST_DATA_DIR.joinpath("vector", "n2k", "n2k_example_cz_correct.zip")
        expected_step_statuses = {"v_unzip": "ok",
                                  "v1_n2k": "ok",
                                  "v2": "ok",
                                  "v3": "ok",
                                  "v4": "ok",
                                  "v_import2pg": "ok",
                                  "v5": "ok",
                                  "v6": "ok",
                                  "v8": "ok",
                                  "v9": "ok",
                                  "v10_unit": "ok",
                                  "v11_n2k": "ok",
                                  "v12": "ok",
                                  "v13": "ok",
                                  "v14": "ok",
                                  "v15": "ok"}
        job_result = dispatch(self.job_uuid, "user_name", self.filepath, "n2k")
        step_statuses = dict((step_status["check_ident"], step_status["status"])
                              for step_status in job_result["steps"])
        self.assertDictEqual(expected_step_statuses, step_statuses)


class Test_rpz(ProductTestCase):
    def test(self):
        self.filepath = TEST_DATA_DIR.joinpath("vector", "rpz", "rpz_LCLU2012_DU007T.zip")
        expected_step_statuses = {"v_unzip": "ok",
                                  "v1_rpz": "ok",
                                  "v2": "ok",
                                  "v3": "ok",
                                  "v4": "ok",
                                  "v_import2pg": "ok",
                                  "v5": "ok",
                                  "v6": "ok",
                                  "v8": "ok",
                                  "v9": "ok",
                                  "v10_unit": "ok",
                                  "v11_rpz": "ok",
                                  "v12": "ok",
                                  "v13": "ok",
                                  "v14_rpz": "ok",
                                  "v15": "ok"}
        job_result = dispatch(self.job_uuid, "user_name", self.filepath, "rpz")
        step_statuses = dict((step_status["check_ident"], step_status["status"])
                              for step_status in job_result["steps"])
        self.assertDictEqual(expected_step_statuses, step_statuses)


class Test_ua_shp(ProductTestCase):
    def test(self):
        self.filepath = TEST_DATA_DIR.joinpath("vector", "ua_shp", "EE003L0_NARVA.shp.zip")
        expected_step_statuses = {"v_unzip": "ok",
                                  "v1_ua_shp": "ok",
                                  "v2": "ok",
                                  "reference.v3": "ok",
                                  "v4": "ok",
                                  "v_import2pg": "ok",
                                  "v5": "ok",
                                  "v6": "ok",
                                  "v8": "ok",
                                  "v9": "ok",
                                  "v10": "ok",
                                  "v11_ua_status": "ok",
                                  "v12_ua": "ok",
                                  "v13": "ok",
                                  "v14": "ok",
                                  "v15": "failed"} # FIXME: replace metadata file.
        job_result = dispatch(self.job_uuid, "user_name", self.filepath, "ua_2012_shp_wo_revised")
        step_statuses = dict((step_status["check_ident"], step_status["status"])
                              for step_status in job_result["steps"])
        self.assertDictEqual(expected_step_statuses, step_statuses)


class Test_ua_gdb(ProductTestCase):
    def test(self):
        self.maxDiff = None
        filepath = TEST_DATA_DIR.joinpath("vector", "ua_gdb", "DK001L2_KOBENHAVN_clip.zip")
        expected_step_statuses = {"v_unzip": "ok",
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
                                  "v9": "ok",
                                  "v10": "failed", # FIXME: replace boundary layer.
                                  "reference.v11_ua_status": "ok",
                                  "revised.v11_ua_status": "ok",
                                  "change.v11_ua_change": "ok",
                                  "reference.v12_ua": "ok",
                                  "revised.v12_ua": "ok",
                                  "v13": "ok",
                                  "reference.v14": "ok",
                                  "revised.v14": "ok",
                                  "combined_change.v14": "ok",
                                  "v15": "failed"} # FIXME: replace metadata file.
        job_result = dispatch(self.job_uuid, "user_name", filepath, "ua_2012_gdb")
        step_statuses = dict((step_status["check_ident"], step_status["status"])
                              for step_status in job_result["steps"])
        self.assertDictEqual(expected_step_statuses, step_statuses)
