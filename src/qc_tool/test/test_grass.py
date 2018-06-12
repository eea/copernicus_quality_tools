#!/usr/bin/env python3
from pathlib import Path
from subprocess import run

from unittest import TestCase
from uuid import uuid4

from qc_tool.common import TEST_DATA_DIR
from qc_tool.wps.manager import create_connection_manager
from qc_tool.wps.manager import create_jobdir_manager

class TestGrass(TestCase):
    def setUp(self):
        self.jobdir_manager = create_jobdir_manager(str(uuid4()))
        self.jobdir_manager.create_dir()

    def test_r11_jobdir(self):
        filepath = str(TEST_DATA_DIR.joinpath("fty_2015_020m_si_03035_d04_test.tif"))
        params = {"area_ha": 25, "job_dir": str(self.jobdir_manager.job_dir)}
        print(self.jobdir_manager.job_dir)
        self.assertIsNotNone(self.jobdir_manager.job_dir, "job_dir should be a valid directory")
        #run_check(filepath, params)

    def test_r11_grass_location(self):
        filepath = str(TEST_DATA_DIR.joinpath("fty_2015_020m_si_03035_d04_test.tif"))
        params = {"area_ha": 25, "job_dir": str(self.jobdir_manager.job_dir)}
        job_dir = self.jobdir_manager.job_dir

        location_path = Path(job_dir, "location")
        #location_path = job_dir
        p = run(["grass72",
                  "-c",
                  filepath,
                 "-e",
                  str(location_path)])

        if p.returncode != 0:
            print("some error creating location!")
        self.assertTrue(location_path.exists())
        self.assertEqual(p.returncode, 0, "GRASS should create the location")

    def test_r11_grass_import(self):
        filepath = str(TEST_DATA_DIR.joinpath("fty_2015_020m_si_03035_d04_test.tif"))

        job_dir = str(self.jobdir_manager.job_dir)
        params = {"area_ha": 25, "job_dir": job_dir}

        # (PREPARE) creating a location
        location_path = Path(job_dir, "location")
        p1 = run(["grass72",
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
        print(p2.stderr)
        print(p2.stdout)

        self.assertEqual(p2.returncode, 0, "GRASS should import the dataset via r.in.gdal")

    def test_r11_grass_clump(self):
        filepath = str(TEST_DATA_DIR.joinpath("fty_2015_020m_si_03035_d04_test.tif"))

        job_dir = str(self.jobdir_manager.job_dir)
        params = {"area_ha": 25, "job_dir": job_dir}

        # (PREPARE) creating a location
        location_path = Path(job_dir, "location")
        p1 = run(["grass72",
                  "-c",
                  filepath,
                  "-e",
                  str(location_path)], check=True)

        if p1.returncode != 0:
            print("some error creating location!")

        # import dataset
        mapset_path = Path(location_path, "PERMANENT")
        p2 = run(["grass72",
                  str(mapset_path),
                  "--exec",
                  "r.in.gdal",
                  "input={:s}".format(filepath),
                  "output=inpfile"],
                  check=True)

        # run clump
        p3 = run(["grass72",
                  str(mapset_path),
                  "--exec",
                  "r.clump",
                  "input=inpfile",
                  "output=clumps",
                  "title=clumps"],
                 check=True)

        self.assertEqual(p3.returncode, 0, "GRASS should create the clumps.")

    def test_r11_grass_volume(self):
        filepath = str(TEST_DATA_DIR.joinpath("fty_2015_020m_si_03035_d04_test.tif"))

        job_dir = str(self.jobdir_manager.job_dir)
        params = {"area_ha": 25, "job_dir": job_dir}

        # (PREPARE) creating a location
        location_path = Path(job_dir, "location")
        p1 = run(["grass72",
                  "-c",
                  filepath,
                  "-e",
                  str(location_path)], check=True)

        if p1.returncode != 0:
            print("some error creating location!")

        # import dataset
        mapset_path = Path(location_path, "PERMANENT")
        p2 = run(["grass72",
                  str(mapset_path),
                  "--exec",
                  "r.in.gdal",
                  "input={:s}".format(filepath),
                  "output=inpfile"],
                  check=True)

        # run clump
        p3 = run(["grass72",
                  str(mapset_path),
                  "--exec",
                  "r.clump",
                  "input=inpfile",
                  "output=clumps",
                  "title=clumps"],
                 check=True)

        # run volume
        p4 = run(["grass72",
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

    def test_r11_grass_build(self):
        filepath = str(TEST_DATA_DIR.joinpath("fty_2015_020m_si_03035_d04_test.tif"))

        job_dir = str(self.jobdir_manager.job_dir)
        params = {"area_ha": 25, "job_dir": job_dir}

        # (PREPARE) creating a location
        location_path = Path(job_dir, "location")
        p1 = run(["grass72",
                  "-c",
                  filepath,
                  "-e",
                  str(location_path)], check=True)

        if p1.returncode != 0:
            print("some error creating location!")

        # import dataset
        mapset_path = Path(location_path, "PERMANENT")
        p2 = run(["grass72",
                  str(mapset_path),
                  "--exec",
                  "r.in.gdal",
                  "input={:s}".format(filepath),
                  "output=inpfile"],
                  check=True)

        # run clump
        p3 = run(["grass72",
                  str(mapset_path),
                  "--exec",
                  "r.clump",
                  "input=inpfile",
                  "output=clumps",
                  "title=clumps"],
                 check=True)

        # run volume
        p4 = run(["grass72",
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
        p5 = run(["grass72",
                  str(mapset_path),
                  "--exec",
                  "v.build",
                  "map=clump_centroids",
                  "--verbose"],
                 check=True)
        self.assertEqual(p5.returncode, 0, "GRASS should build clump_centroids layer.")

    def test_r11_grass_extract(self):
        filepath = str(TEST_DATA_DIR.joinpath("fty_2015_020m_si_03035_d04_test.tif"))

        job_dir = str(self.jobdir_manager.job_dir)
        params = {"area_ha": 25, "job_dir": job_dir}

        # (PREPARE) creating a location
        location_path = Path(job_dir, "location")
        p1 = run(["grass72",
                  "-c",
                  filepath,
                  "-e",
                  str(location_path)], check=True)

        if p1.returncode != 0:
            print("some error creating location!")

        # import dataset
        mapset_path = Path(location_path, "PERMANENT")
        p2 = run(["grass72",
                  str(mapset_path),
                  "--exec",
                  "r.in.gdal",
                  "input={:s}".format(filepath),
                  "output=inpfile"],
                  check=True)

        # run clump
        p3 = run(["grass72",
                  str(mapset_path),
                  "--exec",
                  "r.clump",
                  "input=inpfile",
                  "output=clumps",
                  "title=clumps"],
                 check=True)

        # run volume
        p4 = run(["grass72",
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
        p5 = run(["grass72",
                  str(mapset_path),
                  "--exec",
                  "v.build",
                  "map=clump_centroids",
                  "--verbose"],
                 check=True)

        # remove db columns
        p5 = run(["grass72",
                  str(mapset_path),
                  "--exec",
                  "v.db.dropcolumn",
                  "map=clump_centroids",
                  "columns=volume,average,sum"],
                 check=True)

        # print connection
        p6 = run(["grass72",
                  str(mapset_path),
                  "--exec",
                  "v.db.connect",
                  "-c",
                  "map=clump_centroids"],
                 check=True)

        # extract features with count<5
        p7 = run(["grass72",
                  str(mapset_path),
                  "--exec",
                  "v.extract",
                  "input=clump_centroids",
                  "output=lessmmu_centroids",
                  "where=\"(count<5)\""],
                 check=True)

        self.assertEqual(p7.returncode, 0, "GRASS should extract the feature with lessmmu")

    def test_r11_grass_export(self):
        #filepath = str(TEST_DATA_DIR.joinpath("fty_2015_020m_si_03035_d04_test.tif"))
        filepath = str(TEST_DATA_DIR.joinpath("FTY_2015_020m_eu_03035_d04_full.tif"))

        job_dir = str(self.jobdir_manager.job_dir)
        params = {"area_ha": 25, "job_dir": job_dir}

        # (PREPARE) creating a location
        location_path = Path(job_dir, "location")
        p1 = run(["grass72",
                  "-c",
                  filepath,
                  "-e",
                  str(location_path)], check=True)

        if p1.returncode != 0:
            print("some error creating location!")

        # import dataset
        mapset_path = Path(location_path, "PERMANENT")
        p2 = run(["grass72",
                  str(mapset_path),
                  "--exec",
                  "r.in.gdal",
                  "input={:s}".format(filepath),
                  "output=inpfile"],
                  check=True)

        # run clump
        p3 = run(["grass72",
                  str(mapset_path),
                  "--exec",
                  "r.clump",
                  "input=inpfile",
                  "output=clumps",
                  "title=clumps"],
                 check=True)

        # run volume
        p4 = run(["grass72",
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
        p5 = run(["grass72",
                  str(mapset_path),
                  "--exec",
                  "v.build",
                  "map=clump_centroids",
                  "--verbose"],
                 check=True)

        # remove db columns
        p6 = run(["grass72",
                  str(mapset_path),
                  "--exec",
                  "v.db.dropcolumn",
                  "map=clump_centroids",
                  "columns=volume,average,sum"],
                 check=True)

        # export to shp
        out_path = TEST_DATA_DIR.joinpath(self.jobdir_manager.job_dir.name)
        p7 = run(["grass72",
                  str(mapset_path),
                  "--exec",
                  "v.out.ogr",
                  "input=clump_centroids",
                  "output={:s}".format(str(out_path)),
                  "format=ESRI_Shapefile",
                  "output_layer=clump_centroids"],
                 check=True)

        self.assertEqual(p7.returncode, 0, "GRASS should export lessmmu_centroids to shapefile.")

    def test_r11(self):
        from qc_tool.wps.raster_check.r11 import run_check
        filepath = str(TEST_DATA_DIR.joinpath("fty_2015_020m_si_03035_d04_test.tif"))
        params = {"area_ha": 25, "job_dir": str(self.jobdir_manager.job_dir)}
        run_check(filepath, params)

    def tearDown(self):
        self.jobdir_manager.remove_dir()
