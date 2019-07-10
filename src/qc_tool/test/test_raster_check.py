#!/usr/bin/env python3


from unittest import skipIf
from osgeo import gdal
from osgeo import osr
import numpy as np

from qc_tool.common import CONFIG
from qc_tool.common import TEST_DATA_DIR
from qc_tool.test.helper import RasterCheckTestCase


class Test_naming(RasterCheckTestCase):
    def test(self):
        from qc_tool.raster.naming import run_check
        params = {"unzip_dir": TEST_DATA_DIR.joinpath("raster",
                                                     "fty_100m",
                                                     "fty_2015_100m_mt_03035_d02_clip"),
                  "aoi_codes": ["mt", "eu"],
                  "extensions": [".tif", ".tfw"],
                  "extract_reference_year": True,
                  "layer_names": {"layer_1": "^fty_(?P<reference_year>[0-9]{4})_100m_(?P<aoi_code>.+)_[0-9]{5}.*.tif$"}
                 }
        status = self.status_class()
        run_check(params, status)
        self.assertEqual("ok", status.status)
        self.assertEqual("mt", status.params["aoi_code"])
        self.assertEqual("2015", status.status_properties["reference_year"])
        self.assertEqual("fty_2015_100m_mt_03035_d02_clip.tif", status.params["raster_layer_defs"]["layer_1"]["src_layer_name"])

    def test_two_layers(self):
        from qc_tool.raster.naming import run_check
        params = {"unzip_dir": TEST_DATA_DIR.joinpath("raster",
                                                     "checks",
                                                     "mmu"),
                  "extensions": [".tif"],
                  "layer_names": {"layer_1": "^test_raster1.tif$",
                                  "layer_2": "^mmu_raster_incorrect.tif$",
                                  "layer_3": "^mmu_raster_correct.tif"}
                 }
        status = self.status_class()
        run_check(params, status)
        self.assertEqual("ok", status.status)
        self.assertEqual("test_raster1.tif", status.params["raster_layer_defs"]["layer_1"]["src_layer_name"])
        self.assertEqual(TEST_DATA_DIR.joinpath("raster", "checks", "mmu", "test_raster1.tif"),
                         status.params["raster_layer_defs"]["layer_1"]["src_filepath"])
        self.assertEqual("mmu_raster_incorrect.tif", status.params["raster_layer_defs"]["layer_2"]["src_layer_name"])
        self.assertEqual(TEST_DATA_DIR.joinpath("raster", "checks", "mmu", "mmu_raster_incorrect.tif"),
                         status.params["raster_layer_defs"]["layer_2"]["src_filepath"])
        self.assertEqual("mmu_raster_correct.tif", status.params["raster_layer_defs"]["layer_3"]["src_layer_name"])
        self.assertEqual(TEST_DATA_DIR.joinpath("raster", "checks", "mmu", "mmu_raster_correct.tif"),
                         status.params["raster_layer_defs"]["layer_3"]["src_filepath"])

    def test_missing_layer(self):
        from qc_tool.raster.naming import run_check
        params = {"unzip_dir": TEST_DATA_DIR.joinpath("raster",
                                                     "checks",
                                                     "mmu"),
                  "extensions": [".tif"],
                  "layer_names": {"layer_1": "^test_raster1.tif$",
                                  "layer_2": "^mmu_raster_incorrect.tif$",
                                  "layer_3": "^mmu_raster_correct.tif",
                                  "layer_4": "^non_existent_raster.tif"}
                 }
        status = self.status_class()
        run_check(params, status)
        self.assertEqual("aborted", status.status)
        self.assertIn("Can not find layer_4 layer.", status.messages)

    def test_excessive_layers(self):
        from qc_tool.raster.naming import run_check
        params = {"unzip_dir": TEST_DATA_DIR.joinpath("raster",
                                                     "checks",
                                                     "mmu"),
                  "extensions": [".tif"],
                  "layer_names": {"layer_1": "^test_raster1.tif$"}
                 }
        status = self.status_class()
        run_check(params, status)
        self.assertEqual("failed", status.status)

    def test_incorrect_aoi_code(self):
        from qc_tool.raster.naming import run_check
        params = {"unzip_dir": TEST_DATA_DIR.joinpath("raster",
                                                     "checks",
                                                     "mmu"),
                  "extensions": [".tif"],
                  "layer_names": {"layer_1": "^test_(?P<aoi_code>[a-z0-9]+).tif$"},
                  "aoi_codes": ["aoi_1", "aoi_2"]
                 }
        status = self.status_class()
        run_check(params, status)
        self.assertEqual("aborted", status.status)
        self.assertIn("Layer test_raster1.tif has illegal AOI code raster1.", status.messages)


class Test_value(RasterCheckTestCase):
    def setUp(self):
        super().setUp()
        layer_filepath = TEST_DATA_DIR.joinpath("raster", "checks", "gap", "complete_raster_100m_testaoi.tif")
        layer_defs = {"layer_1": {"src_filepath": layer_filepath, "src_layer_name": layer_filepath.name}}
        self.params.update({"raster_layer_defs": layer_defs,
                            "layers": ["layer_1"]})


    def test(self):
        from qc_tool.raster.value import run_check

        self.params.update({"validcodes": [0, 1]})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_fail(self):
        from qc_tool.raster.value import run_check

        self.params.update({"validcodes": [1, 2, 255]})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status, "Value raster check should fail "
                                                  "if the raster has invalid codes.")
        self.assertIn("invalid values: 0.", status.messages[0])


class Test_gap(RasterCheckTestCase):
    def setUp(self):
        super().setUp()
        layer_filepath1 = TEST_DATA_DIR.joinpath("raster", "checks", "gap", "complete_raster_100m_testaoi.tif")
        layer_filepath2 = TEST_DATA_DIR.joinpath("raster", "checks", "gap", "incomplete_raster_100m_testaoi.tif")
        layer_defs = {"layer_1": {"src_filepath": layer_filepath1, "src_layer_name": layer_filepath1.name},
                      "layer_2": {"src_filepath": layer_filepath2, "src_layer_name": layer_filepath2.name}}
        self.params.update({"raster_layer_defs": layer_defs})

    def test(self):
        from qc_tool.raster.gap import run_check

        self.params.update({"layers": ["layer_1"],
                            "aoi_code": "testaoi",
                            "outside_area_code": 255,
                            "mask": "test",
                            "boundary_dir": TEST_DATA_DIR.joinpath("boundaries"),
                            "tmp_dir": self.jobdir_manager.tmp_dir,
                            "output_dir": self.jobdir_manager.output_dir,
                            "step_nr": 1})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status, "Gap raster check should pass "
                                              "if the raster does not have NoData values inside the AOI.")
    def test_cancelled(self):
        from qc_tool.raster.gap import run_check
        self.params.update({"layers": ["layer_2"],
                            "aoi_code": "non-existing-country",
                            "outside_area_code": 255,
                            "mask": "test",
                            "boundary_dir": TEST_DATA_DIR.joinpath("boundaries"),
                            "tmp_dir": self.jobdir_manager.tmp_dir,
                            "output_dir": self.jobdir_manager.output_dir,
                            "step_nr": 1})
        status = self.status_class()
        run_check(self.params, status)
        self.assertIn("cancelled", status.messages[0])

    def test_gaps_found(self):
        from qc_tool.raster.gap import run_check
        self.params.update({"layers": ["layer_2"],
                            "aoi_code": "testaoi",
                            "outside_area_code": 255,
                            "mask": "test",
                            "boundary_dir": TEST_DATA_DIR.joinpath("boundaries"),
                            "tmp_dir": self.jobdir_manager.tmp_dir,
                            "output_dir": self.jobdir_manager.output_dir,
                            "step_nr": 1})
        status = self.status_class()
        run_check(self.params, status)
        self.assertIn("has 1237 gap pixels", status.messages[0])
        self.assertIn("s01_incomplete_raster_100m_testaoi_gap_warning.gpkg", status.attachment_filenames)
        self.assertTrue(self.params["output_dir"].joinpath(status.attachment_filenames[0]).exists())


class Test_tile(RasterCheckTestCase):
    def setUp(self):
        super().setUp()

        self.params["tmp_dir"] = self.jobdir_manager.tmp_dir
        self.params["output_dir"] = self.jobdir_manager.output_dir
        self.params["max_blocksize"] = 256
        raster_src_filepath = self.params["tmp_dir"].joinpath("test_raster.tif")
        self.params["raster_layer_defs"] = {"raster_1": {"src_filepath": str(raster_src_filepath),
                                                         "src_layer_name": "raster_1"}}
        self.params["layers"] = ["raster_1"]
        self.params["step_nr"] = 1

    def test(self):

        # Create an example tiled raster layer
        width = 2000
        height = 256
        xmin = 10000
        ymax = 10000
        pixel_size = 5

        # Prepare raster dataset.
        mem_drv = gdal.GetDriverByName("MEM")
        mem_ds = mem_drv.Create("memory", width, height, 1, gdal.GDT_Byte)
        mem_srs = osr.SpatialReference()
        mem_srs.ImportFromEPSG(3035)
        mem_ds.SetProjection(mem_srs.ExportToWkt())
        mem_ds.SetGeoTransform((xmin, pixel_size, 0, ymax, 0, -pixel_size))
        mem_ds.GetRasterBand(1).Fill(0)

        # Store raster dataset.
        dest_driver = gdal.GetDriverByName("GTiff")
        dest_ds = dest_driver.CreateCopy(str(self.params["raster_layer_defs"]["raster_1"]["src_filepath"]),
                                         mem_ds, False, options=["TILED=YES"])

        # Remove temporary datasource and datasets from memory.
        mem_dsrc = None
        mem_ds = None
        dest_ds = None

        # Run check on tiled raster
        from qc_tool.raster.tile import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_aborted(self):
        # Create an example tiled raster layer
        width = 2000
        height = 256
        xmin = 10000
        ymax = 10000
        pixel_size = 5

        # Prepare raster dataset.
        mem_drv = gdal.GetDriverByName("MEM")
        mem_ds = mem_drv.Create("memory", width, height, 1, gdal.GDT_Byte)
        mem_srs = osr.SpatialReference()
        mem_srs.ImportFromEPSG(3035)
        mem_ds.SetProjection(mem_srs.ExportToWkt())
        mem_ds.SetGeoTransform((xmin, pixel_size, 0, ymax, 0, -pixel_size))
        mem_ds.GetRasterBand(1).Fill(0)

        # Store raster dataset.
        dest_driver = gdal.GetDriverByName("GTiff")
        dest_ds = dest_driver.CreateCopy(str(self.params["raster_layer_defs"]["raster_1"]["src_filepath"]),
                                         mem_ds, False, options=["TILED=NO"])

        # Remove temporary datasource and datasets from memory.
        mem_dsrc = None
        mem_ds = None
        dest_ds = None

        # Run check on untiled raster
        from qc_tool.raster.tile import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status)
        print(status.messages)


class Test_mmu(RasterCheckTestCase):
    def setUp(self):
        super().setUp()
        layer_filepath1 = TEST_DATA_DIR.joinpath("raster", "checks", "mmu", "mmu_raster_correct.tif")
        layer_filepath2 = TEST_DATA_DIR.joinpath("raster", "checks", "mmu", "mmu_raster_incorrect.tif")
        layer_defs = {"layer_correct": {"src_filepath": layer_filepath1, "src_layer_name": layer_filepath1.name},
                      "layer_incorrect": {"src_filepath": layer_filepath2, "src_layer_name": layer_filepath2.name}}
        self.params.update({"raster_layer_defs": layer_defs})


    def test_dirs(self):
        self.assertTrue(self.jobdir_manager.job_dir.exists(), "job_dir directory must exist.")
        self.assertTrue(self.jobdir_manager.output_dir.exists(), "output_dir directory must exist.")

    def test_ok(self):
        from qc_tool.raster.mmu import run_check
        self.params.update({"layers": ["layer_correct"],
                            "area_pixels": 13,
                            "nodata_value": 0,
                            "output_dir": self.jobdir_manager.output_dir,
                            "step_nr": 1})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status, "Raster check r11 should pass for test raster with patches >= 13 pixels.")

    def test_fail(self):
        from qc_tool.raster.mmu import run_check
        self.params.update({"layers": ["layer_incorrect"],
                            "area_pixels": 13,
                            "nodata_value": 0,
                            "output_dir": self.jobdir_manager.output_dir,
                            "step_nr": 1})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status, "MMU raster check should fail for raster with patches < 13 pixels.")
        self.assertIn("1", status.messages[0], "There should be 1 object with MMU error.")
        self.assertIn("s01_mmu_raster_incorrect_lessmmu_error.gpkg", status.attachment_filenames)


@skipIf(CONFIG["skip_inspire_check"], "INSPIRE check has been disabled.")
class Test_inspire(RasterCheckTestCase):
    def setUp(self):
        super().setUp()
        xml_dir = TEST_DATA_DIR.joinpath("metadata")
        filepath_good = xml_dir.joinpath("inspire-good.tif")
        filepath_missing = xml_dir.joinpath("inspire-missing-metadata.tif")
        filepath_bad = xml_dir.joinpath("inspire-bad.tif")
        layer_defs = {"layer_good": {"src_filepath": filepath_good, "src_layer_name": filepath_good.name},
                      "layer_missing": {"src_filepath": filepath_missing, "src_layer_name": filepath_missing.name},
                      "layer_bad": {"src_filepath": filepath_bad, "src_layer_name": filepath_bad.name}}
        self.params.update({"raster_layer_defs": layer_defs,
                            "step_nr": 1,
                            "output_dir": self.jobdir_manager.output_dir})

    def test(self):
        from qc_tool.raster.inspire import run_check
        self.params.update({"layers":["layer_good"]})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status, "INSPIRE raster check should pass for raster with valid metadata file.")

    def test_missing_xml_fail(self):
        from qc_tool.raster.inspire import run_check
        self.params.update({"layers": ["layer_missing"]})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status, "INSPIRE raster check should fail for raster with missing xml file.")

    def test_fail(self):
        from qc_tool.raster.inspire import run_check
        self.params.update({"layers": ["layer_bad"]})
        self.params["skip_inspire_check"] = False
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status, "INSPIRE raster check should fail for raster with non-compliant xml file.")


class Test_color(RasterCheckTestCase):
    def setUp(self):
        super().setUp()
        layer_filepath1 = TEST_DATA_DIR.joinpath("raster", "checks", "mmu", "mmu_raster_correct.tif")
        layer_defs = {"layer_1": {"src_filepath": layer_filepath1, "src_layer_name": layer_filepath1.name}}
        self.params.update({"raster_layer_defs": layer_defs})

    def test(self):
        from qc_tool.raster.color import run_check
        self.params.update({"layers": ["layer_1"],
                            "colors": {"0": [240, 240, 240],
                                       "1": [70, 158, 74],
                                       "2": [28, 92, 36],
                                       "254": [153, 153, 153],
                                       "255": [0, 0, 0]}})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status, "Color raster check with correct colors should pass.")

    def test_fail(self):
        from qc_tool.raster.color import run_check
        self.params.update({"layers": ["layer_1"],
                            "colors": {"0": [240, 240, 240],
                                       "1": [70, 158, 74],
                                       "2": [28, 92, 36],
                                       "254": [153, 153, 153],
                                       "255": [0, 0, 99]}})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status, "Color raster check with incorrect colors should fail.")
