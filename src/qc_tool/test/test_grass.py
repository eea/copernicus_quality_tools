#!/usr/bin/env python3


from pathlib import Path
from subprocess import run

from qc_tool.common import TEST_DATA_DIR
from qc_tool.test.helper import RasterCheckTestCase


GRASS_VERSION = "grass72"


class TestGrass(RasterCheckTestCase):
    def test_grass_jobdir(self):
        self.assertIsNotNone(self.jobdir_manager.job_dir, "job_dir should be a valid directory")

    def test_grass_location(self):
        filepath = str(TEST_DATA_DIR.joinpath("raster", "checks", "r11", "r11_raster_correct.tif"))
        tmp_dir = self.jobdir_manager.tmp_dir

        location_path = tmp_dir.joinpath("location")
        p = run([GRASS_VERSION,
                  "-c",
                  filepath,
                 "-e",
                  str(location_path)])

        self.assertTrue(location_path.exists())
        self.assertEqual(p.returncode, 0, "GRASS should create the location without error.")

    def test_grass_import(self):
        filepath = str(TEST_DATA_DIR.joinpath("raster", "checks", "r11", "r11_raster_correct.tif"))

        tmp_dir = self.jobdir_manager.tmp_dir
        location_path = tmp_dir.joinpath("location")
        p1 = run([GRASS_VERSION,
                  "-c",
                  filepath,
                  "-e",
                  str(location_path)], check=True)

        mapset_path = Path(location_path, "PERMANENT")
        p2 = run(["grass72",
                  str(mapset_path),
                  "--exec",
                  "r.in.gdal",
                  "input={:s}".format(filepath),
                  "output=inpfile"],
                  check=True)

        self.assertEqual(0, p2.returncode, "GRASS should import the dataset via r.in.gdal without errors.")
