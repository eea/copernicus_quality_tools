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
                                                     "fty_2018_100m_eu_03035_d02_clip"),
                  "aoi_codes": ["mt", "eu"],
                  "extensions": [".tif"],
                  "extract_reference_year": True,
                  "layer_names": {"layer_1": "^fty_(?P<reference_year>[0-9]{4})_100m_(?P<aoi_code>.+)_[0-9]{5}.*.tif$"}
                 }
        status = self.status_class()
        run_check(params, status)
        self.assertEqual("ok", status.status)
        self.assertEqual("eu", status.params["aoi_code"])
        self.assertEqual("2018", status.status_properties["reference_year"])
        self.assertEqual("fty_2018_100m_eu_03035_d02_clip.tif", status.params["raster_layer_defs"]["layer_1"]["src_layer_name"])

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
        self.assertIn("The layer_4 layer name does not match naming convention.", status.messages)

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
        self.mask_filepath = self.jobdir_manager.tmp_dir.joinpath("boundaries", "raster", "mask_default_010m_aoi01.tif")
        self.layer_filepath = self.jobdir_manager.tmp_dir.joinpath("raster_010m_aoi01.tif")

        layer_filepath1 = TEST_DATA_DIR.joinpath("raster", "checks", "gap", "complete_raster_100m_testaoi.tif")
        layer_filepath2 = TEST_DATA_DIR.joinpath("raster", "checks", "gap", "incomplete_raster_100m_testaoi.tif")
        layer_defs = {"layer_1": {"src_filepath": layer_filepath1, "src_layer_name": layer_filepath1.name},
                      "layer_2": {"src_filepath": layer_filepath2, "src_layer_name": layer_filepath2.name},
                      "layer_3": {"src_filepath": self.layer_filepath, "src_layer_name": self.layer_filepath.name}}
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

    def test_inside_mask(self):
        # Prepare mask.
        mask = [[0, 0, 0, 0, 0, 0, 0, 0],
                [0, 1, 1, 1, 1, 0, 0, 0],
                [0, 1, 1, 1, 1, 0, 0, 0],
                [0, 0, 0, 1, 1, 0, 0, 0],
                [0, 1, 0, 1, 1, 0, 0, 0],
                [0, 0, 0, 0, 0, 0, 0, 0]]
        RasterCheckTestCase.create_raster(self.mask_filepath, np.array(mask), 10, ulx=5000, uly=3000)

        # Prepare raster located completely inside the mask.
        layer = [[2, 1, 1, 1, 9],
                 [1, 1, 1, 1, 9],
                 [9, 9, 1, 1, 9],
                 [1, 9, 1, 1, 9]]
        RasterCheckTestCase.create_raster(self.layer_filepath, np.array(layer), 10, ulx=5010, uly=2990)

        self.params.update({"layers": ["layer_3"],
                            "boundary_dir": self.jobdir_manager.tmp_dir.joinpath("boundaries"),
                            "tmp_dir": self.jobdir_manager.tmp_dir,
                            "output_dir": self.jobdir_manager.output_dir,
                            "aoi_code": "aoi01",
                            "outside_area_code": 9,
                            "step_nr": 1})

        from qc_tool.raster.gap import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_bigger_than_mask(self):
        mask = [[0, 1, 1, 1, 0],
                [1, 1, 1, 1, 0],
                [0, 0, 1, 1, 0],
                [1, 0, 1, 1, 0]]
        RasterCheckTestCase.create_raster(self.mask_filepath, np.array(mask), 10, ulx=5010, uly=2990)

        layer = [[0, 0, 0, 0, 0, 0, 0, 0],
                 [0, 1, 1, 1, 1, 0, 0, 0],
                 [0, 1, 1, 1, 1, 0, 0, 0],
                 [0, 0, 0, 1, 1, 0, 0, 0],
                 [0, 1, 0, 1, 1, 0, 0, 0],
                 [0, 0, 0, 0, 0, 0, 0, 0]]
        RasterCheckTestCase.create_raster(self.layer_filepath, np.array(layer), 10, ulx=5000, uly=3000)


        RasterCheckTestCase.create_raster(self.layer_filepath, np.array(layer), 10, ulx=5010, uly=2990)

        self.params.update({"layers": ["layer_3"],
                            "boundary_dir": self.jobdir_manager.tmp_dir.joinpath("boundaries"),
                            "tmp_dir": self.jobdir_manager.tmp_dir,
                            "output_dir": self.jobdir_manager.output_dir,
                            "aoi_code": "aoi01",
                            "outside_area_code": 9,
                            "step_nr": 1})

        from qc_tool.raster.gap import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_outside_mask(self):
        # Prepare mask.
        mask = [[0, 0, 0, 0, 0, 0, 0, 0],
                [0, 1, 1, 1, 1, 0, 0, 0],
                [0, 1, 1, 1, 1, 0, 0, 0],
                [0, 0, 0, 1, 1, 0, 0, 0],
                [0, 1, 0, 1, 1, 0, 0, 0],
                [0, 0, 0, 0, 0, 0, 0, 0]]
        RasterCheckTestCase.create_raster(self.mask_filepath, np.array(mask), 10, ulx=5000, uly=3000)

        # Prepare raster located completely outside the mask.
        layer = [[2, 1, 1],
                 [1, 1, 1],
                 [9, 9, 1]]
        RasterCheckTestCase.create_raster(self.layer_filepath, np.array(layer), 10, ulx=4900, uly=3100)

        self.params.update({"layers": ["layer_3"],
                            "boundary_dir": self.jobdir_manager.tmp_dir.joinpath("boundaries"),
                            "tmp_dir": self.jobdir_manager.tmp_dir,
                            "output_dir": self.jobdir_manager.output_dir,
                            "aoi_code": "aoi01",
                            "outside_area_code": 9,
                            "step_nr": 1})

        from qc_tool.raster.gap import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_intersects_mask_upper_left(self):
        # Prepare mask.
        mask = [[0, 0, 0, 0, 0, 0, 0, 0],
                [0, 1, 1, 1, 1, 0, 0, 0],
                [0, 1, 1, 1, 1, 0, 0, 0],
                [0, 0, 0, 1, 1, 0, 0, 0],
                [0, 1, 0, 1, 1, 0, 0, 0],
                [0, 0, 0, 0, 0, 0, 0, 0]]
        RasterCheckTestCase.create_raster(self.mask_filepath, np.array(mask), 10, ulx=5000, uly=3000)

        # Prepare raster located partially outside the mask.
        layer = [[2, 1, 1, 2],
                 [1, 1, 1, 9],
                 [9, 9, 2, 2]]
        RasterCheckTestCase.create_raster(self.layer_filepath, np.array(layer), 10, ulx=4990, uly=3010)

        self.params.update({"layers": ["layer_3"],
                            "boundary_dir": self.jobdir_manager.tmp_dir.joinpath("boundaries"),
                            "tmp_dir": self.jobdir_manager.tmp_dir,
                            "output_dir": self.jobdir_manager.output_dir,
                            "aoi_code": "aoi01",
                            "outside_area_code": 9,
                            "step_nr": 1})

        from qc_tool.raster.gap import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_intersects_mask_lower_right(self):
        # Prepare mask.
        mask = [[0, 0, 0, 0, 0, 0, 0, 0],
                [0, 1, 1, 1, 1, 0, 0, 0],
                [0, 1, 1, 1, 1, 0, 0, 0],
                [0, 0, 0, 1, 1, 0, 0, 0],
                [0, 1, 0, 1, 1, 0, 0, 0],
                [0, 0, 0, 0, 0, 0, 0, 0]]
        RasterCheckTestCase.create_raster(self.mask_filepath, np.array(mask), 10, ulx=5000, uly=3000)

        # Prepare raster located partially outside the mask.
        layer = [[2, 1, 1, 2],
                 [1, 1, 1, 9],
                 [9, 9, 2, 2]]
        RasterCheckTestCase.create_raster(self.layer_filepath, np.array(layer), 10, ulx=5050, uly=2960)

        self.params.update({"layers": ["layer_3"],
                            "boundary_dir": self.jobdir_manager.tmp_dir.joinpath("boundaries"),
                            "tmp_dir": self.jobdir_manager.tmp_dir,
                            "output_dir": self.jobdir_manager.output_dir,
                            "aoi_code": "aoi01",
                            "outside_area_code": 9,
                            "step_nr": 1})

        from qc_tool.raster.gap import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

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
        self.assertIn("s01_incomplete_raster_100m_testaoi_gap_warning.tif", status.attachment_filenames)
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


class Test_mmu(RasterCheckTestCase):
    def setUp(self):
        super().setUp()
        self.tmp_raster = self.jobdir_manager.tmp_dir.joinpath("test_raster1.tif")
        layer_defs = {"layer1": {"src_filepath": self.tmp_raster, "src_layer_name": self.tmp_raster.name}}
        self.params.update({"raster_layer_defs": layer_defs})

    def test_dirs(self):
        self.assertTrue(self.jobdir_manager.job_dir.exists(), "job_dir directory must exist.")
        self.assertTrue(self.jobdir_manager.output_dir.exists(), "output_dir directory must exist.")

    def test(self):
        # Prepare raster dataset.
        data = [[0, 0, 0, 0, 0, 0, 0, 0],
                [0, 1, 1, 1, 1, 0, 9, 0],
                [0, 1, 1, 1, 1, 0, 0, 0],
                [0, 0, 0, 1, 1, 0, 0, 0],
                [9, 1, 0, 1, 1, 0, 0, 0],
                [9, 0, 0, 0, 0, 0, 0, 0]]
        RasterCheckTestCase.create_raster(self.tmp_raster, np.array(data), 10)

        self.params.update({"layers": ["layer1"],
                            "area_pixels": 10,
                            "nodata_value": 9,
                            "neighbour_exception_codes": [9],
                            "groupcodes": [],
                            "output_dir": self.jobdir_manager.output_dir,
                            "step_nr": 1})

        from qc_tool.raster.mmu import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.assertEqual(1, len(status.attachment_filenames))
        self.assertIn("s01_test_raster1_lessmmu_exception.gpkg", status.attachment_filenames)
        self.assertEqual(1, len(status.messages))
        self.assertIn("1 exceptional objects under MMU limit", status.messages[0])

    def test_groupcodes(self):
        # Prepare raster dataset.
        data = [[9, 0, 0, 0, 0, 0, 0],
                [9, 0, 1, 2, 2, 0, 0],
                [9, 0, 1, 2, 2, 0, 0],
                [9, 0, 0, 2, 2, 0, 0],
                [9, 1, 0, 0, 0, 0, 0],
                [9, 9, 9, 9, 9, 9, 0]]

        RasterCheckTestCase.create_raster(self.tmp_raster, np.array(data), 10)
        self.params.update(
            {"layers": ["layer1"],
             "area_pixels": 8,
             "nodata_value": 9,
             "neighbour_exception_codes": [9],
             "groupcodes": [[1, 2]],
             "output_dir": self.jobdir_manager.output_dir,
             "step_nr": 1})

        from qc_tool.raster.mmu import run_check
        status = self.status_class()
        run_check(self.params, status)

        self.assertEqual("ok", status.status)
        self.assertEqual(1, len(status.attachment_filenames))
        self.assertIn("s01_test_raster1_lessmmu_exception.gpkg", status.attachment_filenames)
        self.assertEqual(1, len(status.messages))
        self.assertIn("1 exceptional objects under MMU limit", status.messages[0])

    def test_edge_patches(self):
        # Prepare raster dataset.
        data = [[1, 0, 1, 1, 1, 0, 0],
                [0, 0, 0, 0, 0, 0, 0],
                [0, 1, 1, 1, 1, 0, 0],
                [0, 1, 1, 1, 1, 0, 1],
                [1, 0, 0, 0, 0, 1, 1],
                [1, 1, 1, 1, 0, 1, 1]]

        RasterCheckTestCase.create_raster(self.tmp_raster, np.array(data), 10)
        self.params.update(
            {"layers": ["layer1"],
             "area_pixels": 8,
             "nodata_value": 9,
             "groupcodes": [],
             "output_dir": self.jobdir_manager.output_dir,
             "step_nr": 1})

        from qc_tool.raster.mmu import run_check
        status = self.status_class()
        run_check(self.params, status)

        self.assertEqual("ok", status.status)
        self.assertEqual(1, len(status.attachment_filenames))
        self.assertIn("s01_test_raster1_lessmmu_exception.gpkg", status.attachment_filenames)
        self.assertEqual(1, len(status.messages))
        self.assertIn("5 exceptional objects under MMU limit", status.messages[0])

    def test_fail(self):
        # Prepare raster dataset with a patch smaller than MMU.
        data = np.zeros((4000, 3000), dtype=int)
        data[2047, 1000] = 1
        data[2047, 1001] = 1
        data[2048, 1000] = 1
        data[2048, 1001] = 1
        data[2047, 1111] = 1
        data[2048, 1111] = 1
        data[2049, 1111] = 1

        RasterCheckTestCase.create_raster(self.tmp_raster, np.array(data), 10)
        self.params.update(
            {"layers": ["layer1"],
             "area_pixels": 4,
             "nodata_value": 9,
             "groupcodes": [],
             "output_dir": self.jobdir_manager.output_dir,
             "step_nr": 1})

        from qc_tool.raster.mmu import run_check
        status = self.status_class()
        run_check(self.params, status)

        self.assertEqual("failed", status.status)
        self.assertEqual(1, len(status.attachment_filenames))
        self.assertIn("s01_test_raster1_lessmmu_error.gpkg", status.attachment_filenames)
        self.assertEqual(1, len(status.messages))
        self.assertIn("1 error objects under MMU limit", status.messages[0])


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


@skipIf(CONFIG["skip_inspire_check"], "INSPIRE check has been disabled.")
class Test_inspire(RasterCheckTestCase):
    def setUp(self):
        super().setUp()
        self.xml_dir = TEST_DATA_DIR.joinpath("metadata")
        self.params["tmp_dir"] = self.jobdir_manager.tmp_dir
        self.params["output_dir"] = self.jobdir_manager.output_dir
        self.params["layers"] = ["layer0"]
        self.params["step_nr"] = 1

    def test(self):
        from qc_tool.raster.inspire import run_check
        self.params["raster_layer_defs"] = {"layer0": {"src_filepath": self.xml_dir.joinpath("inspire_good.tif")}}
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.assertIn("s01_inspire_good_inspire_report.html", status.attachment_filenames)
        self.assertIn("s01_inspire_good_inspire_log.txt", status.attachment_filenames)

    def test_missing_xml_fail(self):
        from qc_tool.raster.inspire import run_check
        self.params["raster_layer_defs"] = {"layer0": {"src_filepath": self.xml_dir.joinpath("inspire_missing_xml.tif")}}
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)

    def test_xml_format_fail(self):
        from qc_tool.raster.inspire import run_check
        self.params["raster_layer_defs"] = {"layer0": {"src_filepath": self.xml_dir.joinpath("inspire_invalid_xml.tif")}}
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)
        self.assertEqual(2, len(status.messages))
        self.assertIn("The xml file inspire_invalid_xml.xml does not contain a <gmd:MD_Metadata> top-level element.", status.messages[1])

    def test_fail(self):
        from qc_tool.raster.inspire import run_check
        self.params["raster_layer_defs"] = {"layer0": {"src_filepath": self.xml_dir.joinpath("inspire_bad.tif")}}
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)
        self.assertIn("s01_inspire_bad_inspire_report.html", status.attachment_filenames)
        self.assertIn("s01_inspire_bad_inspire_log.txt", status.attachment_filenames)

    def test_fail2(self):
        from qc_tool.raster.inspire import run_check
        self.params["raster_layer_defs"] = {"layer0": {"src_filepath": self.xml_dir.joinpath("IMD_2018_010m_eu_03035_test.tif")}}
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)
        self.assertIn("s01_IMD_2018_010m_eu_03035_test_inspire_report.html", status.attachment_filenames)
        self.assertIn("s01_IMD_2018_010m_eu_03035_test_inspire_log.txt", status.attachment_filenames)
