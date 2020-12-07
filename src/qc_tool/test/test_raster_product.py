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

    def test_fty_2018_010m(self):
        """High resolution forest type (FTY) - 10m"""
        product_ident = "fty_2018_010m"
        filepath = self.raster_data_dir.joinpath("fty_010m", "FTY_2018_010m_eu_03035_v0_1.zip")

        expected_step_results = ["ok"] * 13

        # inspire check is skipped
        expected_step_results[2] = "skipped"
        # fty_010m has extra checks raster.tile and raster.mmu
        expected_step_results[11] = "failed"

        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident, (3,))
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_statuses, self.show_messages(job_result))

    def test_fty_2018_100m(self):
        """High resolution forest type (FTY) - 100m"""
        product_ident = "fty_2018_100m"
        filepath = self.raster_data_dir.joinpath("fty_100m", "fty_2018_100m_eu_03035_v0_1.zip")

        expected_step_results = ["ok"] * 12
        expected_step_results[2] = "skipped"

        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident, (3,))
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_statuses, self.show_messages(job_result))

    def test_gra_2018_010m(self):
        """High resolution grassland (GRA) - 10m"""
        product_ident = "gra_2018_010m"
        filepath = self.raster_data_dir.joinpath("gra_010m", "GRA_2018_010m_eu_03035_v0_1.zip")

        expected_step_results = ["ok"] * 13
        expected_step_results[2] = "skipped"

        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident, (3,))
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_statuses, self.show_messages(job_result))

    def test_gra_2018_100m(self):
        """High resolution grassland (GRA) - 100m"""
        product_ident = "gra_2018_100m"
        filepath = self.raster_data_dir.joinpath("gra_100m", "GRA_2018_100m_eu_03035_v0_1.zip")

        expected_step_results = ["ok"] * 12
        expected_step_results[2] = "skipped"
        # gra_2018_100m has mismatching attributes.
        expected_step_results[3] = "failed"

        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident, (3,))
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_statuses, self.show_messages(job_result))

    def test_imc_1518_020m(self):
        """High resolution imperviousness change (IMC) - 20m"""
        product_ident = "imc_1518_020m"
        filepath = self.raster_data_dir.joinpath("imc_020m", "IMC_1518_020m_eu_03035_v0_1.zip")

        expected_step_results = ["ok"] * 12
        # inspire check is skipped
        expected_step_results[2] = "skipped"
        # imc_1518_020m has mismatching attributes.
        expected_step_results[3] = "failed"
        # imc_1518_020m has mismatching bit depth.
        expected_step_results[7] = "failed"

        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident, (3,))
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_statuses, self.show_messages(job_result))

    def test_imc_1518_100m(self):
        """High resolution imperviousness change (IMC) - 100m"""
        product_ident = "imc_1518_100m"
        filepath = self.raster_data_dir.joinpath("imc_100m", "IMC_1518_100m_eu_03035_v0_1.zip")

        expected_step_results = ["ok"] * 12
        # inspire check is skipped
        expected_step_results[2] = "skipped"
        # imc_1518_100mm has mismatching attributes.
        expected_step_results[3] = "failed"
        # imc_1518_100m has mismatching bit depth.
        expected_step_results[7] = "failed"

        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident, (3,))
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_statuses, self.show_messages(job_result))

    def test_imd_2018_010m(self):
        """High resolution imperviousness density (IMD) - 10m"""
        product_ident = "imd_2018_010m"
        filepath = self.raster_data_dir.joinpath("imd_010m", "IMD_2018_010m_eu_03035_v0_1.zip")

        expected_step_results = ["ok"] * 12
        # inspire check is skipped
        expected_step_results[2] = "skipped"
        # imd_2018_010m has mismatching attributes
        expected_step_results[3] = "failed"

        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident, (3,))
        print(job_result)
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_statuses, self.show_messages(job_result))

    def test_imd_2018_100m(self):
        """High resolution imperviousness density (IMD) - 100m"""
        product_ident = "imd_2018_100m"
        filepath = self.raster_data_dir.joinpath("imd_100m", "IMD_2018_100m_eu_03035_v1_0.zip")

        expected_step_results = ["ok"] * 12
        # inspire check is skipped
        expected_step_results[2] = "skipped"
        # imd_2018_100m has mismatching attributes
        expected_step_results[3] = "failed"

        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident, (3,))
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_statuses, self.show_messages(job_result))

    def test_tcd_2018_010m(self):
        """High resolution tree cover density (TCD) - 10m"""
        product_ident = "tcd_2018_010m"
        filepath = self.raster_data_dir.joinpath("tcd_010m", "TCD_2018_010m_eu_03035_v0_1.zip")

        expected_step_results = ["ok"] * 12
        # inspire check is skipped
        expected_step_results[2] = "skipped"

        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident, (3,))
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_statuses, self.show_messages(job_result))

    def test_tcd_2018_100m(self):
        """High resolution tree cover density (TCD) - 100m"""
        product_ident = "tcd_2018_100m"
        filepath = self.raster_data_dir.joinpath("tcd_100m", "TCD_2018_100m_eu_03035_v0_1.zip")

        expected_step_results = ["ok"] * 12
        # inspire check is skipped
        expected_step_results[2] = "skipped"

        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident, (3,))
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_statuses, self.show_messages(job_result))

    def test_swf_2015_100m(self):
        """High resolution small woody features - 100m raster"""
        product_ident = "swf_2015_100m"
        filepath = TEST_DATA_DIR.joinpath("raster", "swf_100m", "swf_2015_100m_eu_3035_v1_1.zip")

        expected_step_results = ["ok"] * 10
        # inspire check is skipped
        expected_step_results[2] = "skipped"

        job_result = dispatch(self.job_uuid, "user_name", filepath, product_ident, (3,))
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_results)

    def test_ua2012_dhm(self):
        """Urban Atlas 2012 Building Heights - 10m raster"""
        product_ident = "ua2012_dhm"
        filepath = TEST_DATA_DIR.joinpath("raster", "ua2012_dhm", "EE003Ly_NARVA_ua2012_dhm.zip")

        expected_step_results = ["ok"] * 12
        # inspire check is skipped
        expected_step_results[2] = "skipped"

        job_result = dispatch(self.job_uuid, "user_name", filepath, product_ident, (3,))
        print(job_result)
        step_results = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_results)

    def test_general_raster(self):
        """General raster product"""
        product_ident = "general_raster"
        filepath = self.raster_data_dir.joinpath("general_raster", "general_raster.zip")

        expected_step_results = ["ok"] * 9
        # inspire check is skipped
        expected_step_results[2] = "skipped"

        job_result = dispatch(self.job_uuid, self.username, filepath, product_ident, (3,))
        step_statuses = [step_result["status"] for step_result in job_result["steps"]]
        self.assertListEqual(expected_step_results, step_statuses)
