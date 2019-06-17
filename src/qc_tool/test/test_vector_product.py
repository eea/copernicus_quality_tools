#!/usr/bin/env python3


import json
from pathlib import Path

from qc_tool.common import TEST_DATA_DIR
from qc_tool.test.helper import ProductTestCase
from qc_tool.worker.dispatch import dispatch


class Test_clc(ProductTestCase):
    def test(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb.zip")
        expected_step_results = ["ok"] * 24
        job_result = dispatch(self.job_uuid, "user_name", filepath, "clc2012")
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_results)


class Test_clc_status(ProductTestCase):
    def test_status_json(self):
        from qc_tool.common import load_job_result
        filepath = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb.zip")
        job_result = dispatch(self.job_uuid, "user_name", filepath, "clc2012", [])
        job_result_from_file = load_job_result(self.job_uuid)
        self.assertEqual(job_result, job_result_from_file,
                         "Job result returned by dispatch() must be the same as job result stored in json file.")


class Test_n2k(ProductTestCase):
    def test(self):
        self.filepath = TEST_DATA_DIR.joinpath("vector", "n2k", "n2k_example_cz_correct.zip")
        expected_step_results = ["ok"] * 15
        job_result = dispatch(self.job_uuid, "user_name", self.filepath, "n2k")
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_results)


class Test_rpz(ProductTestCase):
    def test(self):
        self.filepath = TEST_DATA_DIR.joinpath("vector", "rpz", "rpz_LCLU2012_DU007T.zip")
        expected_step_results = ["ok"] * 15
        job_result = dispatch(self.job_uuid, "user_name", self.filepath, "rpz")
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_results)


class Test_swf_vec_ras(ProductTestCase):
    def test(self):
        self.filepath = TEST_DATA_DIR.joinpath("vector_raster", "swf_2015_vec_ras", "swf_2015_vec_ras_FR_3035_123_pt01.zip")
        expected_step_results = ["ok"] * 28
        job_result = dispatch(self.job_uuid, "user_name", self.filepath, "swf_2015_vec_ras")
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_results)


class Test_ua_shp(ProductTestCase):
    def test(self):
        self.filepath = TEST_DATA_DIR.joinpath("vector", "ua_shp", "EE003L0_NARVA.shp.zip")
        expected_step_results = ["ok"] * 15
        job_result = dispatch(self.job_uuid, "user_name", self.filepath, "ua_2012_shp_wo_change")
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_results)


class Test_ua_gdb(ProductTestCase):
    def test(self):
        self.maxDiff = None
        filepath = TEST_DATA_DIR.joinpath("vector", "ua_gdb", "DK001L2_KOBENHAVN_clip.zip")
        expected_step_results = ["ok"] * 21
        job_result = dispatch(self.job_uuid, "user_name", filepath, "ua_2012_gdb")
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_results)
