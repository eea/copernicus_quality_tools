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
        # vector.inspire check is skipped
        expected_step_results[7] = "skipped"

        job_result = dispatch(self.job_uuid, "user_name", filepath, "clc2012", (8,))
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


class Test_n2k_2006(ProductTestCase):
    def test(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "n2k", "gpkg", "N2K_DU001A_Status2006_LCLU_v1_20200519.gpkg.zip")
        expected_step_results = ["ok"] * 17
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"

        job_result = dispatch(self.job_uuid, "user_name", filepath, "n2k_2006", (6,))
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_results)


class Test_n2k_2012(ProductTestCase):
    def test(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "n2k", "gpkg", "N2K_DU001A_Status2012_LCLU_v1_20200519.gpkg.zip")
        expected_step_results = ["ok"] * 17
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"

        job_result = dispatch(self.job_uuid, "user_name", filepath, "n2k_2012", (6,))
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_results)


class Test_n2k_2018(ProductTestCase):
    def test(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "n2k", "gpkg", "N2K_DU001A_Status2018_LCLU_v1_20200519.gpkg.zip")
        expected_step_results = ["ok"] * 17
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"

        job_result = dispatch(self.job_uuid, "user_name", filepath, "n2k_2018", (6,))
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_results)


class Test_n2k_2012_change(ProductTestCase):
    def test(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "n2k", "gpkg", "N2K_DU001A_Change2006-2012_LCLU_v1_20200520.gpkg.zip")
        expected_step_results = ["ok"] * 16
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"

        job_result = dispatch(self.job_uuid, "user_name", filepath, "n2k_2012_change", (6,))
        print(job_result)
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_results)


class Test_n2k_2018_change(ProductTestCase):
    def test(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "n2k", "gpkg", "N2K_DU001A_Change2012-2018_LCLU_v1_20200520.gpkg.zip")
        expected_step_results = ["ok"] * 16
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"

        job_result = dispatch(self.job_uuid, "user_name", filepath, "n2k_2018_change", (6,))
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_results)


class Test_rpz_2012(ProductTestCase):
    def test(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "rpz", "rpz_LCLU2012_DU007T.zip")
        expected_step_results = ["ok"] * 16
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"

        job_result = dispatch(self.job_uuid, "user_name", filepath, "rpz_2012", (6,))
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_results)


class Test_rpz_2018(ProductTestCase):
    def test(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "rpz", "rpz_DU001B_lclu_2018_2012_v01.gpkg.zip")
        expected_step_results = ["ok"] * 18
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"

        job_result = dispatch(self.job_uuid, "user_name", filepath, "rpz_2018", (6,))
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_results)


class Test_swf_vec_ras(ProductTestCase):
    def test(self):
        filepath = TEST_DATA_DIR.joinpath("vector_raster", "swf_2015_vec_ras", "swf_2015_vec_ras_FR_3035_123_pt01.zip")
        expected_step_results = ["ok"] * 30
        # vector.inspire check is skipped
        expected_step_results[16] = "skipped"
        # vector.area in the testing data does not match
        expected_step_results[20] = "failed"

        job_result = dispatch(self.job_uuid, "user_name", filepath, "swf_2015_vec_ras", (17,))
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_results)
        self.assertListEqual(['Layer vector has error features with row number: 10.'],
                             job_result["steps"][20]["messages"])


class Test_ua2012(ProductTestCase):
    def test_gpkg(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "ua", "gpkg", "EE003L1_NARVA_UA2012.gpkg.zip")
        expected_step_results = ["ok"] * 16
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"

        job_result = dispatch(self.job_uuid, "user_name", filepath, "ua2012", (6,))
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.maxDiff = None
        self.assertListEqual(expected_step_results, step_results)


class Test_ua2018(ProductTestCase):
    def test_gpkg(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "ua", "gpkg", "EE003L1_NARVA_UA2018.gpkg.zip")
        expected_step_results = ["ok"] * 16
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"

        job_result = dispatch(self.job_uuid, "user_name", filepath, "ua2018", (6,))
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.maxDiff = None
        self.assertListEqual(expected_step_results, step_results)


class Test_ua_change_2012_2018(ProductTestCase):
    def test_gpkg(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "ua", "gpkg", "EE003L1_NARVA_change_2012_2018.gpkg.zip")
        expected_step_results = ["ok"] * 16
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"

        job_result = dispatch(self.job_uuid, "user_name", filepath, "ua_change_2012_2018", (6,))
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.maxDiff = None
        self.assertListEqual(expected_step_results, step_results)

    def test_very_long_layer_name(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "ua", "gpkg", "UK568L1_CHESHIRE_WEST_AND_CHESTER_change_2012_2018.zip")
        expected_step_results = ["ok"] * 16
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"
        expected_step_results[13] = "skipped"

        job_result = dispatch(self.job_uuid, "user_name", filepath, "ua_change_2012_2018", (6, 14))
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.maxDiff = None
        self.assertListEqual(expected_step_results, step_results)


class Test_ua2018_stl(ProductTestCase):
    def test_gpkg(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "ua", "gpkg", "EE003L1_NARVA_UA2018_stl.gpkg.zip")
        expected_step_results = ["ok"] * 14
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"

        job_result = dispatch(self.job_uuid, "user_name", filepath, "ua2018_stl", (6,))
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.maxDiff = None
        self.assertListEqual(expected_step_results, step_results)

class Test_cz_2012(ProductTestCase):
    def test_gdb(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "cz", "gpkg", "CZ_2012_DU001_3035_V1_2.gpkg.zip")
        expected_step_results = ["ok"] * 17
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"

        job_result = dispatch(self.job_uuid, "user_name", filepath, "cz_2012", (6,))
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.maxDiff = None
        self.assertListEqual(expected_step_results, step_results)

class Test_cz_2018(ProductTestCase):
    def test_gdb(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "cz", "gpkg", "CZ_2018_DU001_3035_V1_2.gpkg.zip")
        expected_step_results = ["ok"] * 17
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"

        job_result = dispatch(self.job_uuid, "user_name", filepath, "cz_2018", (6,))
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.maxDiff = None
        self.assertListEqual(expected_step_results, step_results)

class Test_cz_change_2012_2018(ProductTestCase):
    def test_gdb(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "cz", "gpkg", "CZ_change_2012_2018_DU001_3035_V1_2.gpkg.zip")
        expected_step_results = ["ok"] * 16
        # vector.inspire check is skipped
        expected_step_results[5] = "skipped"

        job_result = dispatch(self.job_uuid, "user_name", filepath, "cz_change_2012_2018", (6,))
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.maxDiff = None
        self.assertListEqual(expected_step_results, step_results)

