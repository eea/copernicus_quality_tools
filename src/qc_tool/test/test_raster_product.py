#!/usr/bin/env python3


from qc_tool.common import TEST_DATA_DIR
from qc_tool.test.helper import ProductTestCase
from qc_tool.wps.dispatch import dispatch


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
    def test_fty_020m(self):
        product_ident = "fty_020m"
        filepath = self.raster_data_dir.joinpath(product_ident, "FTY_2015_020m_mt_03035_d04_clip.zip")
        # fty_020m has extra check r11 (raster MMU)
        self.expected_step_statuses.append("ok")
        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident)
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(self.expected_step_statuses, step_statuses, self.show_messages(job_result))

    # High resolution forest type (FTY) - 100m
    def test_fty_100m(self):
        product_ident = "fty_100m"
        filepath = self.raster_data_dir.joinpath(product_ident, "fty_2015_100m_mt_03035_d02_clip.zip")
        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident)
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(self.expected_step_statuses, step_statuses, self.show_messages(job_result))

    # High resolution grassland (GRA) - 20m
    def test_gra_020m(self):
        product_ident = "gra_020m"
        filepath = self.raster_data_dir.joinpath(product_ident, "GRA_2015_020m_mt_03035_V1_clip.zip")
        # gra_020m has extra check r11 (raster MMU)
        self.expected_step_statuses.append("ok")
        # gra_020m has mismatching attributes
        self.expected_step_statuses[3] = "failed"
        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident)
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(self.expected_step_statuses, step_statuses, self.show_messages(job_result))

    # High resolution grassland (GRA) - 100m
    def test_gra_100m(self):
        product_ident = "gra_100m"
        filepath = self.raster_data_dir.joinpath(product_ident, "GRA_2015_100m_mt_03035_V1_clip.zip")
        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident)
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(self.expected_step_statuses, step_statuses, self.show_messages(job_result))

    # High resolution imperviousness change (IMC) - 20m
    def test_imc_020m(self):
        product_ident = "imc_020m"
        filepath = self.raster_data_dir.joinpath(product_ident, "IMC_1215_020m_mt_03035_d02_clip.zip")
        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident)
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(self.expected_step_statuses, step_statuses, self.show_messages(job_result))

    # High resolution imperviousness change (IMC) - 100m
    def test_imc_100m(self):
        product_ident = "imc_100m"
        filepath = self.raster_data_dir.joinpath(product_ident, "IMC_1215_100m_mt_03035_d02_clip.zip")
        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident)
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(self.expected_step_statuses, step_statuses, self.show_messages(job_result))

    # High resolution imperviousness density (IMD) - 20m
    def test_imd_020m(self):
        product_ident = "imd_020m"
        filepath = self.raster_data_dir.joinpath(product_ident, "IMD_2015_020m_mt_03035_d04_clip.zip")
        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident)
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(self.expected_step_statuses, step_statuses, self.show_messages(job_result))

    # High resolution imperviousness density (IMD) - 100m
    def test_imd_100m(self):
        product_ident = "imd_100m"
        filepath = self.raster_data_dir.joinpath(product_ident, "IMD_2015_100m_mt_03035_d02_clip.zip")
        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident)
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(self.expected_step_statuses, step_statuses, self.show_messages(job_result))

    # High resolution tree cover density (TCD) - 20m
    def test_tcd_020m(self):
        product_ident = "tcd_020m"
        filepath = self.raster_data_dir.joinpath(product_ident, "TCD_2015_020m_mt_03035_d04_clip.zip")
        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident)
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(self.expected_step_statuses, step_statuses, self.show_messages(job_result))

    # High resolution tree cover density (TCD) - 100m
    def test_tcd_100m(self):
        product_ident = "tcd_100m"
        filepath = self.raster_data_dir.joinpath(product_ident, "TCD_2015_100m_mt_03035_d03_clip.zip")
        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident)
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(self.expected_step_statuses, step_statuses, self.show_messages(job_result))

    # High resolution water and wetness (WAW) - 20m
    def test_waw_020m(self):
        product_ident = "waw_020m"
        filepath = self.raster_data_dir.joinpath(product_ident, "WAW_2015_020m_mt_03035_d06_clip.zip")
        # completeness check is cancelled due to unavailable raster mask.
        self.expected_step_statuses[10] = "cancelled"
        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident)
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(self.expected_step_statuses, step_statuses)

    # High resolution water and wetness (WAW) - 100m
    def test_waw_100m(self):
        product_ident = "waw_100m"
        filepath = self.raster_data_dir.joinpath(product_ident, "WAW_2015_100m_mt_03035_d02_clip.zip")
        # completeness check is cancelled due to unavailable raster mask.
        self.expected_step_statuses[10] = "cancelled"
        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident)
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(self.expected_step_statuses, step_statuses)
