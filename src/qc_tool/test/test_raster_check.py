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


class TestR11(RasterCheckTestCase):
    def test_r11_dirs(self):
        self.assertTrue(self.jobdir_manager.job_dir.exists(), "job_dir directory must exist.")
        self.assertTrue(self.jobdir_manager.tmp_dir.exists(), "tmp_dir directory must exist.")
        self.assertTrue(self.jobdir_manager.output_dir.exists(), "output_dir directory must exist.")

    def test_r11(self):
        from qc_tool.wps.raster_check.r11 import run_check
        params = {"filepath": TEST_DATA_DIR.joinpath("raster", "checks", "r11", "r11_raster_incorrect.tif"),
                  "area_m2": 5000,
                  "tmp_dir": self.jobdir_manager.tmp_dir,
                  "output_dir": self.jobdir_manager.output_dir}
        status = self.status_class()
        run_check(params, status)
        self.assertNotIn("GRASS GIS error", status.messages[0])

    def test_r11_correct_pass(self):
        from qc_tool.wps.raster_check.r11 import run_check
        params = {"filepath": TEST_DATA_DIR.joinpath("raster", "checks", "r11", "r11_raster_correct.tif"),
                  "area_m2": 5000,
                  "tmp_dir": self.jobdir_manager.tmp_dir,
                  "output_dir": self.jobdir_manager.output_dir}
        status = self.status_class()
        run_check(params, status)
        self.assertEqual("ok", status.status, "Raster check r11 should pass for raster with patches > 0.5 ha.")

    def test_r11_incorrect_fail(self):
        from qc_tool.wps.raster_check.r11 import run_check
        params = {"filepath": TEST_DATA_DIR.joinpath("raster", "checks", "r11", "r11_raster_incorrect.tif"),
                  "area_m2": 5000,
                  "tmp_dir": self.jobdir_manager.tmp_dir,
                  "output_dir": self.jobdir_manager.output_dir}
        status = self.status_class()
        run_check(params, status)
        self.assertNotIn("GRASS GIS error", status.messages[0])
        self.assertEqual("failed", status.status, "Raster check r11 should fail for raster with patches < 0.5 ha.")
        self.assertIn("3", status.messages[0], "There should be 3 polygons with MMU error.")
        # Note: We should also test the existence of the lessmmu_areas.shp shapefile inside output_dir.


class TestR15(RasterCheckTestCase):
    def test_r15_correct_pass(self):
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

    def test_r15_incorrect_fail(self):
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
