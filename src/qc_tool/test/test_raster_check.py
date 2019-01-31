#!/usr/bin/env python3


from qc_tool.common import TEST_DATA_DIR
from qc_tool.test.helper import RasterCheckTestCase


class TestR2(RasterCheckTestCase):
    def test_r2(self):
        from qc_tool.wps.raster_check.r2 import run_check
        params = {"filepath": TEST_DATA_DIR.joinpath("raster",
                                                     "fty_100m",
                                                     "fty_2015_100m_mt_03035_d02_clip",
                                                     "fty_2015_100m_mt_03035_d02_clip.tif"),
                  "country_codes": ["mt", "eu"],
                  "extensions": [".tif", ".tfw", ".xml|.tif.xml", ".tif.vat.dbf"],
                  "file_name_regex": "^fty_(?P<reference_year>[0-9]{4})_100m_(?P<country_code>.+)_[0-9]{5}.*.tif$"}
        status = self.status_class()
        run_check(params, status)
        self.assertEqual("ok", status.status, "raster check r2 should pass")
        self.assertEqual("mt", status.params["country_code"])
        self.assertEqual("2015", status.status_properties["reference_year"])


class TestR9(RasterCheckTestCase):
    def test(self):
        from qc_tool.wps.raster_check.r9 import run_check
        params = {"filepath": TEST_DATA_DIR.joinpath("raster", "checks", "r10", "complete_raster_100m_testaoi.tif"),
                  "validcodes": [0, 1]}
        status = self.status_class()
        run_check(params, status)
        self.assertEqual("ok", status.status)

    def test_fail(self):
        from qc_tool.wps.raster_check.r9 import run_check
        params = {"filepath": TEST_DATA_DIR.joinpath("raster", "checks", "r10", "complete_raster_100m_testaoi.tif"),
                  "validcodes": [1, 2, 255]}
        status = self.status_class()
        run_check(params, status)
        self.assertEqual("failed", status.status, "Raster check r9 should fail "
                                                  "if the raster has invalid codes.")
        self.assertIn("invalid codes: 0.", status.messages[0])


class TestR10(RasterCheckTestCase):
    def test(self):
        from qc_tool.wps.raster_check.r10 import run_check
        params = {"filepath": TEST_DATA_DIR.joinpath("raster", "checks", "r10", "complete_raster_100m_testaoi.tif"),
                  "country_code": "testaoi",
                  "outside_area_code": 255,
                  "mask": "test",
                  "boundary_dir": TEST_DATA_DIR.joinpath("boundaries"),
                  "tmp_dir": self.jobdir_manager.tmp_dir,
                  "output_dir": self.jobdir_manager.output_dir}
        status = self.status_class()
        run_check(params, status)
        self.assertEqual("ok", status.status, "Raster check r10 should pass "
                                              "if the raster does not have NoData values inside the AOI.")
    def test_cancelled(self):
        from qc_tool.wps.raster_check.r10 import run_check
        params = {"filepath": TEST_DATA_DIR.joinpath("raster", "checks", "r10", "incomplete_raster_100m_testaoi.tif"),
                  "country_code": "non-existing-country",
                  "outside_area_code": 255,
                  "mask": "test",
                  "boundary_dir": TEST_DATA_DIR.joinpath("boundaries"),
                  "tmp_dir": self.jobdir_manager.tmp_dir,
                  "output_dir": self.jobdir_manager.output_dir}
        status = self.status_class()
        run_check(params, status)
        self.assertEqual("cancelled", status.status, "r10 should cancel when boundary file cannot be found.")

    def test_fail(self):
        from qc_tool.wps.raster_check.r10 import run_check
        params = {"filepath": TEST_DATA_DIR.joinpath("raster", "checks", "r10", "incomplete_raster_100m_testaoi.tif"),
                  "country_code": "testaoi",
                  "outside_area_code": 255,
                  "mask": "test",
                  "boundary_dir": TEST_DATA_DIR.joinpath("boundaries"),
                  "tmp_dir": self.jobdir_manager.tmp_dir,
                  "output_dir": self.jobdir_manager.output_dir}
        status = self.status_class()
        run_check(params, status)
        self.assertEqual("failed", status.status, "Raster check r10 should fail "
                                                  "if the raster has NoData values in the AOI.")
        self.assertIn("incomplete_raster_100m_testaoi_completeness_error.zip", status.attachment_filenames)
        self.assertTrue(params["output_dir"].joinpath(status.attachment_filenames[0]).exists())


class TestR11(RasterCheckTestCase):
    def test_r11_dirs(self):
        self.assertTrue(self.jobdir_manager.job_dir.exists(), "job_dir directory must exist.")
        self.assertTrue(self.jobdir_manager.output_dir.exists(), "output_dir directory must exist.")

    def test_ok(self):
        from qc_tool.wps.raster_check.r11 import run_check
        params = {"filepath": TEST_DATA_DIR.joinpath("raster", "checks", "r11", "r11_raster_correct.tif"),
                  "area_pixels": 13,
                  "nodata_value": 0,
                  "output_dir": self.jobdir_manager.output_dir}
        status = self.status_class()
        run_check(params, status)
        self.assertEqual("ok", status.status, "Raster check r11 should pass for test raster with patches >= 13 pixels.")

    def test_fail(self):
        from qc_tool.wps.raster_check.r11 import run_check
        params = {"filepath": TEST_DATA_DIR.joinpath("raster", "checks", "r11", "r11_raster_incorrect.tif"),
                  "area_pixels": 13,
                  "nodata_value": 0,
                  "output_dir": self.jobdir_manager.output_dir}
        status = self.status_class()
        run_check(params, status)
        self.assertEqual("failed", status.status, "Raster check r11 should fail for raster with patches < 13 pixels.")
        self.assertIn("1", status.messages[0], "There should be 1 object with MMU error.")
        self.assertIn("r11_raster_incorrect_lessmmu_error.zip", status.attachment_filenames)


class TestR12(RasterCheckTestCase):
    def setUp(self):
        super().setUp()
        self.xml_dir = TEST_DATA_DIR.joinpath("metadata")
        self.params.update({"output_dir": self.jobdir_manager.output_dir})

    def test(self):
        from qc_tool.wps.raster_check.r12 import run_check
        self.params["filepath"] = self.xml_dir.joinpath("inspire-good.tif")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status, "Raster check r12 should pass for raster with valid metadata file.")

    def test_missing_xml_fail(self):
        from qc_tool.wps.raster_check.r12 import run_check
        self.params["filepath"] = self.xml_dir.joinpath("inspire-missing-metadata.tif")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status, "Raster check r12 should fail for raster with missing xml file.")

    def test_fail(self):
        from qc_tool.wps.raster_check.r12 import run_check
        self.params["filepath"] = self.xml_dir.joinpath("inspire-bad.tif")
        self.params["skip_inspire_check"] = False
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status, "Raster check r12 should fail for raster with non-compliant xml file.")


class TestR15(RasterCheckTestCase):
    def test(self):
        from qc_tool.wps.raster_check.r15 import run_check
        params = {"filepath": TEST_DATA_DIR.joinpath("raster", "checks", "r11", "r11_raster_correct.tif"),
                  "colours": {"0": [240, 240, 240],
                              "1": [70, 158, 74],
                              "2": [28, 92, 36],
                              "254": [153, 153, 153],
                              "255": [0, 0, 0]}}
        status = self.status_class()
        run_check(params, status)
        self.assertEqual("ok", status.status, "Check r15 with correct colours should pass.")

    def test_fail(self):
        from qc_tool.wps.raster_check.r15 import run_check
        params = {"filepath": TEST_DATA_DIR.joinpath("raster", "checks", "r11", "r11_raster_correct.tif"),
                  "colours": {"0": [240, 240, 240],
                              "1": [70, 158, 74],
                              "2": [28, 92, 36],
                              "254": [153, 153, 153],
                              "255": [0, 0, 99]}}
        status = self.status_class()
        run_check(params, status)
        self.assertEqual("failed", status.status, "Check r15 with incorrect colours should fail.")
