#!/usr/bin/env python3


from pathlib import Path
from subprocess import run
from unittest import TestCase
from uuid import uuid4

from qc_tool.common import TEST_DATA_DIR
from qc_tool.test.helper import RasterCheckTestCase


GRASS_VERSION = "grass72"


class TestGrass(RasterCheckTestCase):
    def test_grass_jobdir(self):
        self.assertIsNotNone(self.jobdir_manager.job_dir, "job_dir should be a valid directory")

    def test_grass_location(self):
        filepath = str(TEST_DATA_DIR.joinpath("fty_2015_020m_si_03035_d04_test.tif"))
        tmp_dir = self.jobdir_manager.tmp_dir

        location_path = tmp_dir.joinpath("location")
        p = run([GRASS_VERSION,
                  "-c",
                  filepath,
                 "-e",
                  str(location_path)])

        if p.returncode != 0:
            print("some error creating location!")
        self.assertTrue(location_path.exists())
        self.assertEqual(p.returncode, 0, "GRASS should create the location")

    def test_grass_import(self):
        filepath = str(TEST_DATA_DIR.joinpath("fty_2015_020m_si_03035_d04_test.tif"))

        tmp_dir = self.jobdir_manager.tmp_dir
        location_path = tmp_dir.joinpath("location")
        p1 = run([GRASS_VERSION,
                  "-c",
                  filepath,
                  "-e",
                  str(location_path)], check=True)

        if p1.returncode != 0:
            print("some error creating location!")

        mapset_path = Path(location_path, "PERMANENT")
        p2 = run(["grass72",
                  str(mapset_path),
                  "--exec",
                  "r.in.gdal",
                  "input={:s}".format(filepath),
                  "output=inpfile"],
                  check=True)

        self.assertEqual(0, p2.returncode, "GRASS should import the dataset via r.in.gdal")

    def test_grass_clump(self):
        filepath = str(TEST_DATA_DIR.joinpath("fty_2015_020m_si_03035_d04_test.tif"))

        tmp_dir = self.jobdir_manager.tmp_dir

        location_path = tmp_dir.joinpath("location")
        p1 = run(["grass72",
                  "-c",
                  filepath,
                  "-e",
                  str(location_path)], check=True)

        if p1.returncode != 0:
            print("some error creating location!")

        # import dataset
        mapset_path = location_path.joinpath("PERMANENT")
        p2 = run([GRASS_VERSION,
                  str(mapset_path),
                  "--exec",
                  "r.in.gdal",
                  "input={:s}".format(filepath),
                  "output=inpfile"],
                  check=True)

        # run clump
        p3 = run([GRASS_VERSION,
                  str(mapset_path),
                  "--exec",
                  "r.clump",
                  "input=inpfile",
                  "output=clumps",
                  "title=clumps"],
                 check=True)

        self.assertEqual(p3.returncode, 0, "GRASS should create the clumps.")

    def test_grass_volume(self):
        filepath = str(TEST_DATA_DIR.joinpath("fty_2015_020m_si_03035_d04_test.tif"))

        tmp_dir = self.jobdir_manager.tmp_dir

        # (PREPARE) creating a location
        location_path = tmp_dir.joinpath("location")
        p1 = run([GRASS_VERSION,
                  "-c",
                  filepath,
                  "-e",
                  str(location_path)], check=True)

        if p1.returncode != 0:
            print("some error creating location!")

        # import dataset
        mapset_path = location_path.joinpath("PERMANENT")
        p2 = run([GRASS_VERSION,
                  str(mapset_path),
                  "--exec",
                  "r.in.gdal",
                  "input={:s}".format(filepath),
                  "output=inpfile"],
                  check=True)

        # run clump
        p3 = run([GRASS_VERSION,
                  str(mapset_path),
                  "--exec",
                  "r.clump",
                  "input=inpfile",
                  "output=clumps",
                  "title=clumps"],
                 check=True)

        # run volume
        p4 = run([GRASS_VERSION,
                  str(mapset_path),
                  "--exec",
                  "r.volume",
                  "--overwrite",
                  "input=clumps",
                  "clump=clumps",
                  "centroids=clump_centroids",
                  "output=clump_stats"],
                 check=True)

        self.assertEqual(p4.returncode, 0, "GRASS should create the volume and clump_centroids.")

    def test_grass_build(self):
        filepath = str(TEST_DATA_DIR.joinpath("fty_2015_020m_si_03035_d04_test.tif"))

        tmp_dir = self.jobdir_manager.tmp_dir

        # (PREPARE) creating a location
        location_path = tmp_dir.joinpath("location")
        p1 = run([GRASS_VERSION,
                  "-c",
                  filepath,
                  "-e",
                  str(location_path)], check=True)

        if p1.returncode != 0:
            print("some error creating location!")

        # import dataset
        mapset_path = location_path.joinpath("PERMANENT")
        p2 = run([GRASS_VERSION,
                  str(mapset_path),
                  "--exec",
                  "r.in.gdal",
                  "input={:s}".format(filepath),
                  "output=inpfile"],
                  check=True)

        # run clump
        p3 = run([GRASS_VERSION,
                  str(mapset_path),
                  "--exec",
                  "r.clump",
                  "input=inpfile",
                  "output=clumps",
                  "title=clumps"],
                 check=True)

        # run volume
        p4 = run([GRASS_VERSION,
                  str(mapset_path),
                  "--exec",
                  "r.volume",
                  "--overwrite",
                  "input=clumps",
                  "clump=clumps",
                  "centroids=clump_centroids",
                  "output=clump_stats"],
                 check=True)

        # rebuild clump_centroids (necessary in grass72)
        p5 = run([GRASS_VERSION,
                  str(mapset_path),
                  "--exec",
                  "v.build",
                  "map=clump_centroids",
                  "--verbose"],
                 check=True)
        self.assertEqual(p5.returncode, 0, "GRASS should build clump_centroids layer.")

    def test_grass_extract(self):
        filepath = str(TEST_DATA_DIR.joinpath("fty_2015_020m_si_03035_d04_test.tif"))

        tmp_dir = self.jobdir_manager.tmp_dir

        # (PREPARE) creating a location
        location_path = tmp_dir.joinpath("location")
        p1 = run([GRASS_VERSION,
                  "-c",
                  filepath,
                  "-e",
                  str(location_path)], check=True)

        if p1.returncode != 0:
            print("some error creating location!")

        # import dataset
        mapset_path = location_path.joinpath("PERMANENT")
        p2 = run([GRASS_VERSION,
                  str(mapset_path),
                  "--exec",
                  "r.in.gdal",
                  "input={:s}".format(filepath),
                  "output=inpfile"],
                  check=True)

        # run clump
        p3 = run([GRASS_VERSION,
                  str(mapset_path),
                  "--exec",
                  "r.clump",
                  "input=inpfile",
                  "output=clumps",
                  "title=clumps"],
                 check=True)

        # run volume
        p4 = run([GRASS_VERSION,
                  str(mapset_path),
                  "--exec",
                  "r.volume",
                  "--overwrite",
                  "input=clumps",
                  "clump=clumps",
                  "centroids=clump_centroids",
                  "output=clump_stats"],
                 check=True)

        # rebuild clump_centroids topology (necessary in grass72)
        p5 = run([GRASS_VERSION,
                  str(mapset_path),
                  "--exec",
                  "v.build",
                  "map=clump_centroids",
                  "--verbose"],
                 check=True)

        # remove db columns
        p5 = run([GRASS_VERSION,
                  str(mapset_path),
                  "--exec",
                  "v.db.dropcolumn",
                  "map=clump_centroids",
                  "columns=volume,average,sum"],
                 check=True)

        # print connection
        p6 = run([GRASS_VERSION,
                  str(mapset_path),
                  "--exec",
                  "v.db.connect",
                  "-c",
                  "map=clump_centroids"],
                 check=True)

        # extract features with count<5
        p7 = run([GRASS_VERSION,
                  str(mapset_path),
                  "--exec",
                  "v.extract",
                  "input=clump_centroids",
                  "output=lessmmu_centroids",
                  "where=\"(count<5)\""],
                 check=True)

        self.assertEqual(p7.returncode, 0, "GRASS should extract the feature with lessmmu")

    def test_grass_export(self):
        filepath = str(TEST_DATA_DIR.joinpath("fty_2015_020m_si_03035_d04_test.tif"))
        #filepath = str(TEST_DATA_DIR.joinpath("FTY_2015_020m_eu_03035_d04_full.tif"))

        tmp_dir = self.jobdir_manager.tmp_dir

        # (PREPARE) creating a location
        location_path = tmp_dir.joinpath("location")
        p1 = run([GRASS_VERSION,
                  "-c",
                  filepath,
                  "-e",
                  str(location_path)], check=True)

        if p1.returncode != 0:
            print("some error creating location!")

        # import dataset
        mapset_path = location_path.joinpath("PERMANENT")
        p2 = run([GRASS_VERSION,
                  str(mapset_path),
                  "--exec",
                  "r.in.gdal",
                  "input={:s}".format(filepath),
                  "output=inpfile"],
                  check=True)

        # run clump
        p3 = run([GRASS_VERSION,
                  str(mapset_path),
                  "--exec",
                  "r.clump",
                  "input=inpfile",
                  "output=clumps",
                  "title=clumps"],
                 check=True)

        # run volume
        p4 = run([GRASS_VERSION,
                  str(mapset_path),
                  "--exec",
                  "r.volume",
                  "--overwrite",
                  "input=clumps",
                  "clump=clumps",
                  "centroids=clump_centroids",
                  "output=clump_stats"],
                 check=True)

        # rebuild clump_centroids (necessary in grass72)
        p5 = run([GRASS_VERSION,
                  str(mapset_path),
                  "--exec",
                  "v.build",
                  "map=clump_centroids",
                  "--verbose"],
                 check=True)

        # remove db columns
        p6 = run([GRASS_VERSION,
                  str(mapset_path),
                  "--exec",
                  "v.db.dropcolumn",
                  "map=clump_centroids",
                  "columns=volume,average,sum"],
                 check=True)

        # export to shp
        out_path = self.jobdir_manager.output_dir
        p7 = run([GRASS_VERSION,
                  str(mapset_path),
                  "--exec",
                  "v.out.ogr",
                  "input=clump_centroids",
                  "output={:s}".format(str(out_path)),
                  "format=ESRI_Shapefile",
                  "output_layer=clump_centroids"],
                 check=True)

        self.assertEqual(p7.returncode, 0, "GRASS should export lessmmu_centroids to shapefile.")


    def test_grass_alternative(self):
        filepath = str(TEST_DATA_DIR.joinpath("fty_2015_020m_si_03035_d04_test.tif"))

        tmp_dir = self.jobdir_manager.tmp_dir

        # (PREPARE) creating a location
        location_path = tmp_dir.joinpath("location")
        p1 = run([GRASS_VERSION,
                  "-c",
                  filepath,
                  "-e",
                  str(location_path)], check=True)

        if p1.returncode != 0:
            print("some error creating location!")

        # import dataset
        mapset_path = location_path.joinpath("PERMANENT")
        p2 = run([GRASS_VERSION,
                  str(mapset_path),
                  "--exec",
                  "r.in.gdal",
                  "input={:s}".format(filepath),
                  "output=inpfile"],
                  check=True)

        # run r.reclass.area
        p3 = run([GRASS_VERSION,
                  str(mapset_path),
                  "--exec",
                  "r.reclass.area",
                  "--verbose",
                  "input=inpfile",
                  "output=lessmmu_raster",
                  "value=5",
                  "mode=lesser",
                  "method=reclass"],
                 check=True)

        # run r.to.vect
        p4 = run([GRASS_VERSION,
                  str(mapset_path),
                  "--exec",
                  "r.to.vect",
                  "--overwrite",
                  "--verbose",
                  "-s",
                  "-v",
                  "type=area",
                  "input=lessmmu_raster",
                  "output=lessmmu_areas"],
                 check=True)

        # export to shp
        output_dir = self.jobdir_manager.output_dir
        output_dir.mkdir()
        out_shapefile_path = output_dir.joinpath("lessmmu_areas.shp")

        p7 = run([GRASS_VERSION,
                  str(mapset_path),
                  "--exec",
                  "v.out.ogr",
                  "input=lessmmu_areas",
                  "output={:s}".format(str(out_shapefile_path)),
                  "format=ESRI_Shapefile"],
                 check=True)

        self.assertEqual(p7.returncode, 0, "GRASS should export lessmmu_areas to shapefile.")
