#!/usr/bin/env python3


from unittest import skipIf

from qc_tool.common import CONFIG
from qc_tool.common import TEST_DATA_DIR
from qc_tool.test.helper import RasterCheckTestCase


class Test_naming(RasterCheckTestCase):
    def test(self):
        from qc_tool.raster.naming import run_check
        params = {"filepath": TEST_DATA_DIR.joinpath("raster",
                                                     "fty_100m",
                                                     "fty_2015_100m_mt_03035_d02_clip",
                                                     "fty_2015_100m_mt_03035_d02_clip.tif"),
                  "country_codes": ["mt", "eu"],
                  "extensions": [".tif", ".tfw", ".xml|.tif.xml", ".tif.vat.dbf"],
                  "file_name_regex": "^fty_(?P<reference_year>[0-9]{4})_100m_(?P<country_code>.+)_[0-9]{5}.*.tif$"}
        status = self.status_class()
        run_check(params, status)
        self.assertEqual("ok", status.status)
        self.assertEqual("mt", status.params["country_code"])
        self.assertEqual("2015", status.status_properties["reference_year"])


class Test_value(RasterCheckTestCase):
    def test(self):
        from qc_tool.raster.value import run_check
        params = {"filepath": TEST_DATA_DIR.joinpath("raster", "checks", "gap", "complete_raster_100m_testaoi.tif"),
                  "validcodes": [0, 1]}
        status = self.status_class()
        run_check(params, status)
        self.assertEqual("ok", status.status)

    def test_fail(self):
        from qc_tool.raster.value import run_check
        params = {"filepath": TEST_DATA_DIR.joinpath("raster", "checks", "gap", "complete_raster_100m_testaoi.tif"),
                  "validcodes": [1, 2, 255]}
        status = self.status_class()
        run_check(params, status)
        self.assertEqual("failed", status.status, "Value raster check should fail "
                                                  "if the raster has invalid codes.")
        self.assertIn("invalid codes: 0.", status.messages[0])


class Test_gap(RasterCheckTestCase):
    def test(self):
        from qc_tool.raster.gap import run_check
        params = {"filepath": TEST_DATA_DIR.joinpath("raster", "checks", "gap", "complete_raster_100m_testaoi.tif"),
                  "country_code": "testaoi",
                  "outside_area_code": 255,
                  "mask": "test",
                  "boundary_dir": TEST_DATA_DIR.joinpath("boundaries"),
                  "tmp_dir": self.jobdir_manager.tmp_dir,
                  "output_dir": self.jobdir_manager.output_dir,
                  "step_nr": 1}
        status = self.status_class()
        run_check(params, status)
        self.assertEqual("ok", status.status, "Gap raster check should pass "
                                              "if the raster does not have NoData values inside the AOI.")
    def test_cancelled(self):
        from qc_tool.raster.gap import run_check
        params = {"filepath": TEST_DATA_DIR.joinpath("raster", "checks", "gap", "incomplete_raster_100m_testaoi.tif"),
                  "country_code": "non-existing-country",
                  "outside_area_code": 255,
                  "mask": "test",
                  "boundary_dir": TEST_DATA_DIR.joinpath("boundaries"),
                  "tmp_dir": self.jobdir_manager.tmp_dir,
                  "output_dir": self.jobdir_manager.output_dir,
                  "step_nr": 1}
        status = self.status_class()
        run_check(params, status)
        self.assertEqual("cancelled", status.status, "Gap raster check should cancel when boundary file cannot be found.")

    def test_fail(self):
        from qc_tool.raster.gap import run_check
        params = {"filepath": TEST_DATA_DIR.joinpath("raster", "checks", "gap", "incomplete_raster_100m_testaoi.tif"),
                  "country_code": "testaoi",
                  "outside_area_code": 255,
                  "mask": "test",
                  "boundary_dir": TEST_DATA_DIR.joinpath("boundaries"),
                  "tmp_dir": self.jobdir_manager.tmp_dir,
                  "output_dir": self.jobdir_manager.output_dir,
                  "step_nr": 1}
        status = self.status_class()
        run_check(params, status)
        self.assertEqual("failed", status.status, "Gap raster check should fail "
                                                  "if the raster has NoData values in the AOI.")
        self.assertIn("s01_incomplete_raster_100m_testaoi_completeness_error.zip", status.attachment_filenames)
        self.assertTrue(params["output_dir"].joinpath(status.attachment_filenames[0]).exists())


class Test_mmu(RasterCheckTestCase):
    def test_dirs(self):
        self.assertTrue(self.jobdir_manager.job_dir.exists(), "job_dir directory must exist.")
        self.assertTrue(self.jobdir_manager.output_dir.exists(), "output_dir directory must exist.")

    def test_ok(self):
        from qc_tool.raster.mmu import run_check
        params = {"filepath": TEST_DATA_DIR.joinpath("raster", "checks", "mmu", "mmu_raster_correct.tif"),
                  "area_pixels": 13,
                  "nodata_value": 0,
                  "output_dir": self.jobdir_manager.output_dir,
                  "step_nr": 1}
        status = self.status_class()
        run_check(params, status)
        self.assertEqual("ok", status.status, "Raster check r11 should pass for test raster with patches >= 13 pixels.")

    def test_fail(self):
        from qc_tool.raster.mmu import run_check
        params = {"filepath": TEST_DATA_DIR.joinpath("raster", "checks", "mmu", "mmu_raster_incorrect.tif"),
                  "area_pixels": 13,
                  "nodata_value": 0,
                  "output_dir": self.jobdir_manager.output_dir,
                  "step_nr": 1}
        status = self.status_class()
        run_check(params, status)
        self.assertEqual("failed", status.status, "MMU raster check should fail for raster with patches < 13 pixels.")
        self.assertIn("1", status.messages[0], "There should be 1 object with MMU error.")
        self.assertIn("s01_mmu_raster_incorrect_lessmmu_error.zip", status.attachment_filenames)


@skipIf(CONFIG["skip_inspire_check"], "INSPIRE check has been disabled.")
class Test_inspire(RasterCheckTestCase):
    def setUp(self):
        super().setUp()
        self.xml_dir = TEST_DATA_DIR.joinpath("metadata")
        self.params.update({"output_dir": self.jobdir_manager.output_dir,
                            "step_nr": 1})

    def test(self):
        from qc_tool.raster.inspire import run_check
        self.params["filepath"] = self.xml_dir.joinpath("inspire-good.tif")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status, "INSPIRE raster check should pass for raster with valid metadata file.")

    def test_missing_xml_fail(self):
        from qc_tool.raster.inspire import run_check
        self.params["filepath"] = self.xml_dir.joinpath("inspire-missing-metadata.tif")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status, "INSPIRE raster check should fail for raster with missing xml file.")

    def test_fail(self):
        from qc_tool.raster.inspire import run_check
        self.params["filepath"] = self.xml_dir.joinpath("inspire-bad.tif")
        self.params["skip_inspire_check"] = False
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status, "INSPIRE raster check should fail for raster with non-compliant xml file.")


class Test_color(RasterCheckTestCase):
    def test(self):
        from qc_tool.raster.color import run_check
        params = {"filepath": TEST_DATA_DIR.joinpath("raster", "checks", "mmu", "mmu_raster_correct.tif"),
                  "colours": {"0": [240, 240, 240],
                              "1": [70, 158, 74],
                              "2": [28, 92, 36],
                              "254": [153, 153, 153],
                              "255": [0, 0, 0]}}
        status = self.status_class()
        run_check(params, status)
        self.assertEqual("ok", status.status, "Color raster check with correct colors should pass.")

    def test_fail(self):
        from qc_tool.raster.color import run_check
        params = {"filepath": TEST_DATA_DIR.joinpath("raster", "checks", "mmu", "mmu_raster_correct.tif"),
                  "colours": {"0": [240, 240, 240],
                              "1": [70, 158, 74],
                              "2": [28, 92, 36],
                              "254": [153, 153, 153],
                              "255": [0, 0, 99]}}
        status = self.status_class()
        run_check(params, status)
        self.assertEqual("failed", status.status, "Color raster check with incorrect colors should fail.")
