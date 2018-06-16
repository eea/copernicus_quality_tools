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
    def test_r11_jobdir(self):
        self.assertIsNotNone(self.jobdir_manager.job_dir, "job_dir should be a valid directory")

    def test_r11_jobdir_exists(self):
        self.assertIsNotNone(self.jobdir_manager.job_dir.exists(), "job_dir directory must exist.")

    def test_r11(self):
        from qc_tool.wps.raster_check.r11 import run_check
        filepath = str(TEST_DATA_DIR.joinpath("fty_2015_020m_si_03035_d04_test.tif"))
        params = {"area_ha": 0.5, "job_dir": str(self.jobdir_manager.job_dir)}
        result = run_check(filepath, params)
        print(result)
        self.assertEqual("failed", result["status"])
        self.assertNotIn("GRASS GIS error", result["message"])

class TestR15(TestCase):
    def test_r15(self):
        from qc_tool.wps.raster_check.r15 import run_check
        filepath = str(TEST_DATA_DIR.joinpath("fty_2015_020m_si_03035_d04_test.tif"))
        print(type(filepath))
        params = {"colours": {
          "0":[240, 240, 240],
          "1":[70, 158, 74],
          "2":[28, 92, 36],
          "254":[153, 153, 153],
          "255":[0, 0, 1]
        }}
        result = run_check(filepath, params)
