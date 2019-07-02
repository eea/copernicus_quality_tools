#!/usr/bin/env python3


from qc_tool.common import TEST_DATA_DIR
from qc_tool.test.helper import ProductTestCase
from qc_tool.worker.dispatch import dispatch


class Test_Raster(ProductTestCase):
    def show_messages(self, job_result):
        """
        Helper function to display messages of aborted, failed or skipped steps in
        case of test failure.
        """
        msg = ""
        for step_result in job_result["steps"]:
            if step_result["status"] not in ("ok", "skipped"):
                msg += ("[{:s} {:s}]: {:s}\n"
                        .format(step_result["check_ident"], step_result["status"], " ".join(step_result["messages"])))
        return msg

    def setUp(self):
        super().setUp()

        self.maxDiff = None
        self.raster_data_dir = TEST_DATA_DIR.joinpath("raster")
        self.username = "test_username"

        # All steps are expected to finish with ok status by default.
        self.expected_step_statuses = ["ok"] * 13

    # High resolution forest type (FTY) - 20m
    def test_fty_2015_020m(self):
        product_ident = "fty_2015_020m"
        filepath = self.raster_data_dir.joinpath("fty_020m", "FTY_2015_020m_mt_03035_d04_clip.zip")
        # fty_020m has extra check r11 (raster MMU)
        self.expected_step_statuses.append("ok")
        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident)
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(self.expected_step_statuses, step_statuses, self.show_messages(job_result))

    # High resolution forest type (FTY) - 100m
    def test_fty_2015_100m(self):
        product_ident = "fty_2015_100m"
        filepath = self.raster_data_dir.joinpath("fty_100m", "fty_2015_100m_mt_03035_d02_clip.zip")
        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident)
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(self.expected_step_statuses, step_statuses, self.show_messages(job_result))

    # High resolution grassland (GRA) - 20m
    def test_gra_2015_020m(self):
        product_ident = "gra_2015_020m"
        filepath = self.raster_data_dir.joinpath("gra_020m", "GRA_2015_020m_mt_03035_V1_clip.zip")
        # gra_020m has extra check r11 (raster MMU)
        self.expected_step_statuses.append("ok")
        # gra_020m has mismatching attributes
        self.expected_step_statuses[3] = "failed"
        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident)
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(self.expected_step_statuses, step_statuses, self.show_messages(job_result))

    # High resolution grassland (GRA) - 100m
    def test_gra_2015_100m(self):
        product_ident = "gra_2015_100m"
        filepath = self.raster_data_dir.joinpath("gra_100m", "GRA_2015_100m_mt_03035_V1_clip.zip")
        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident)
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(self.expected_step_statuses, step_statuses, self.show_messages(job_result))

    # High resolution imperviousness change (IMC) - 20m
    def test_imc_2015_020m(self):
        product_ident = "imc_2015_020m"
        filepath = self.raster_data_dir.joinpath("imc_020m", "IMC_1215_020m_mt_03035_d02_clip.zip")
        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident)
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(self.expected_step_statuses, step_statuses, self.show_messages(job_result))

    # High resolution imperviousness change (IMC) - 100m
    def test_imc_2015_100m(self):
        product_ident = "imc_2015_100m"
        filepath = self.raster_data_dir.joinpath("imc_100m", "IMC_1215_100m_mt_03035_d02_clip.zip")
        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident)
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(self.expected_step_statuses, step_statuses, self.show_messages(job_result))

    # High resolution imperviousness density (IMD) - 20m
    def test_imd_2015_020m(self):
        product_ident = "imd_2015_020m"
        filepath = self.raster_data_dir.joinpath("imd_020m", "IMD_2015_020m_mt_03035_d04_clip.zip")
        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident)
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(self.expected_step_statuses, step_statuses, self.show_messages(job_result))

    # High resolution imperviousness density (IMD) - 100m
    def test_imd_2015_100m(self):
        product_ident = "imd_2015_100m"
        filepath = self.raster_data_dir.joinpath("imd_100m", "IMD_2015_100m_mt_03035_d02_clip.zip")
        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident)
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(self.expected_step_statuses, step_statuses, self.show_messages(job_result))

    # High resolution tree cover density (TCD) - 20m
    def test_tcd_2015_020m(self):
        product_ident = "tcd_2015_020m"
        filepath = self.raster_data_dir.joinpath("tcd_020m", "TCD_2015_020m_mt_03035_d04_clip.zip")
        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident)
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(self.expected_step_statuses, step_statuses, self.show_messages(job_result))

    # High resolution tree cover density (TCD) - 100m
    def test_tcd_2015_100m(self):
        product_ident = "tcd_2015_100m"
        filepath = self.raster_data_dir.joinpath("tcd_100m", "TCD_2015_100m_mt_03035_d03_clip.zip")
        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident)
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(self.expected_step_statuses, step_statuses, self.show_messages(job_result))

    # High resolution water and wetness (WAW) - 20m
    def test_waw_2015_020m(self):
        product_ident = "waw_2015_020m"
        filepath = self.raster_data_dir.joinpath("waw_020m", "WAW_2015_020m_mt_03035_d06_clip.zip")
        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident)
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(self.expected_step_statuses, step_statuses)

    # High resolution water and wetness (WAW) - 100m
    def test_waw_2015_100m(self):
        product_ident = "waw_2015_100m"
        filepath = self.raster_data_dir.joinpath("waw_100m", "WAW_2015_100m_mt_03035_d02_clip.zip")
        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident)
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(self.expected_step_statuses, step_statuses)

    # High resolution small woody features - 5m raster + vector
    def test_swf_2015_100m(self):
        filepath = TEST_DATA_DIR.joinpath("raster", "swf_100m", "swf_2015_100m_eu_03035_v1_1.zip")
        expected_step_results = ["ok"] * 11
        job_result = dispatch(self.job_uuid, "user_name", filepath, "swf_2015_100m")
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_results)

    # General raster product
    def test_general_raster(self):
        product_ident = "general_raster"
        filepath = self.raster_data_dir.joinpath("general_raster", "general_raster.zip")
        expected_step_statuses = ["ok"] * 9
        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident)
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_statuses, step_statuses)
