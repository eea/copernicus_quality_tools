#!/usr/bin/env python3


from unittest import TestCase

from qc_tool.common import TEST_DATA_DIR
from qc_tool.test.helper import RasterCheckTestCase


class TestR2(TestCase):
    def test_r2(self):
        from qc_tool.wps.raster_check.r2 import run_check
        filepath = str(TEST_DATA_DIR.joinpath("fty_2015_020m_si_03035_d04_test.tif"))
        params = {"country_codes": "(AL|AT|BA|BE|BG|CH|CY|CZ|DE|DK|EE|ES|EU|FI|FR|GR|HR|HU"
                                   "|IE|IS|IT|XK|LI|LT|LU|LV|ME|MK|MT|NL|NO|PL|PT|RO|SE|SI"
                                   "|SK|TR|UK|UK_NI|ES_CN|PT_RAA|PT_RAM|UK_GE|UK_JE|FR_GLP"
                                   "|FR_GUF|FR_MTQ|FR_MYT|FR_REU|PT_RAA_CEG|PT_RAA_WEG)",
                  "extensions": [".tif", ".tfw", ".clr", ".xml", ".tif.vat.dbf"],
                  "file_name_regex": "^fty_[0-9]{4}_020m_countrycode_[0-9]{5}.*.tif$"}
        result = run_check(filepath, params)
        if "message" in result:
            print(result["message"])
        self.assertEqual("ok", result["status"], "raster check r2 should pass")


class TestR11(RasterCheckTestCase):
    def test_r11_dirs(self):
        self.assertTrue(self.jobdir_manager.job_dir.exists(), "job_dir directory must exist.")
        self.assertTrue(self.jobdir_manager.tmp_dir.exists(), "tmp_dir directory must exist.")
        self.assertTrue(self.jobdir_manager.output_dir.exists(), "output_dir directory must exist.")

    def test_r11(self):
        from qc_tool.wps.raster_check.r11 import run_check
        filepath = str(TEST_DATA_DIR.joinpath("r11_raster_incorrect.tif"))
        params = {"area_ha": 0.5,
                  "tmp_dir": self.jobdir_manager.tmp_dir,
                  "output_dir": self.jobdir_manager.output_dir}
        result = run_check(filepath, params)
        self.assertNotIn("GRASS GIS error", result["message"])

    def test_r11_correct_pass(self):
        from qc_tool.wps.raster_check.r11 import run_check
        filepath = str(TEST_DATA_DIR.joinpath("r11_raster_correct.tif"))
        params = {"area_ha": 0.5,
                  "tmp_dir": self.jobdir_manager.tmp_dir,
                  "output_dir": self.jobdir_manager.output_dir}
        result = run_check(filepath, params)
        self.assertEqual("ok", result["status"], "Raster check r11 should pass for raster with patches > 0.5 ha.")

    def test_r11_incorrect_fail(self):
        from qc_tool.wps.raster_check.r11 import run_check
        filepath = str(TEST_DATA_DIR.joinpath("r11_raster_incorrect.tif"))
        params = {"area_ha": 0.5,
                  "tmp_dir": self.jobdir_manager.tmp_dir,
                  "output_dir": self.jobdir_manager.output_dir}
        result = run_check(filepath, params)
        self.assertNotIn("GRASS GIS error", result["message"])
        self.assertEqual("failed", result["status"], "Raster check r11 should fail for raster with patches < 0.5 ha.")
        self.assertIn("3", result["message"], "There should be 3 polygons with MMU error.")
        # Note: We should also test the existence of the lessmmu_areas.shp shapefile inside output_dir.


class TestR15(TestCase):
    def test_r15_correct_pass(self):
        from qc_tool.wps.raster_check.r15 import run_check
        filepath = str(TEST_DATA_DIR.joinpath("r11_raster_correct.tif"))
        params = {"colours": {
          "0":[240, 240, 240],
          "1":[70, 158, 74],
          "2":[28, 92, 36],
          "254":[153, 153, 153],
          "255":[0, 0, 0]
        }}
        result = run_check(filepath, params)
        self.assertEqual("ok", result["status"], "Check r15 with correct colours should pass.")

    def test_r15_incorrect_fail(self):
        from qc_tool.wps.raster_check.r15 import run_check
        filepath = str(TEST_DATA_DIR.joinpath("fty_2015_020m_si_03035_d04_test.tif"))
        params = {"colours": {
          "0":[240, 240, 240],
          "1":[70, 158, 74],
          "2":[28, 92, 36],
          "254":[153, 153, 153],
          "255":[0, 0, 99]
        }}
        result = run_check(filepath, params)
        self.assertEqual("failed", result["status"], "Check r15 with incorrect colours should fail.")
