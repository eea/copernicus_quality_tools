#!/usr/bin/env python3
# -*- coding: utf-8 -*-


from shutil import copyfile

import numpy

from qc_tool.common import TEST_DATA_DIR
from qc_tool.test.helper import RasterCheckTestCase


class TestRasterAoi(RasterCheckTestCase):
    def setUp(self):
        super().setUp()
        boundary_directory = self.jobdir_manager.tmp_dir.joinpath(
            "boundaries", "vector"
        )
        boundary_directory.mkdir(parents=True)
        boundary_filename = "aoi_ua_building_heights.gpkg"
        copyfile(
            TEST_DATA_DIR.joinpath("boundaries", "raster", boundary_filename),
            boundary_directory.joinpath(boundary_filename),
        )
        self.params.update({
            "aoi_code": "city002",
            "boundary_dir": boundary_directory.parent,
            "raster_layer_defs": {
                "raster": {
                    "src_filepath": TEST_DATA_DIR.joinpath(
                        "raster", "checks", "gap",
                        "raster_for_vector_aoi_ok.tif",
                    ),
                },
            },
        })
        self.contract = {
            "validator": "raster",
            "checks": ({
                "source_type": "vector",
                "source": boundary_filename,
                "code_field": "code_city",
                "layers": ("raster",),
            },),
        }

    def run_validation(self):
        from qc_tool.raster.aoi import validate_aoi

        status = self.status_class()
        validate_aoi(self.params, status, self.contract)
        return status

    def test_raster_footprint_overlaps_claimed_boundary(self):
        status = self.run_validation()

        self.assertEqual("ok", status.status)
        self.assertEqual("city002", status.status_properties["aoi_code"])
        self.assertEqual(("raster",), status.params["_aoi_validated_media"])

    def test_raster_footprint_outside_claimed_boundary_aborts(self):
        self.params["aoi_code"] = "city001"

        status = self.run_validation()

        self.assertEqual("aborted", status.status)
        self.assertIsNone(status.params["aoi_code"])
        self.assertIsNone(status.status_properties["aoi_code"])
        self.assertEqual((), status.params["_aoi_validated_media"])
        self.assertIn("does not overlap", status.messages[0])

    def prepare_raster_mask_case(self, raster_x, raster_y):
        raster_boundary_directory = self.params["boundary_dir"].joinpath(
            "raster"
        )
        raster_boundary_directory.mkdir()
        mask_values = numpy.zeros((10, 10), dtype=numpy.uint8)
        mask_values[8:10, 8:10] = 1
        RasterCheckTestCase.create_raster(
            raster_boundary_directory.joinpath("mask_test_010m_claimed.tif"),
            mask_values,
            10,
            ulx=0,
            uly=100,
        )
        raster_filepath = self.jobdir_manager.tmp_dir.joinpath("raster.tif")
        RasterCheckTestCase.create_raster(
            raster_filepath,
            numpy.ones((2, 2), dtype=numpy.uint8),
            10,
            ulx=raster_x,
            uly=raster_y,
        )
        self.params.update({
            "aoi_code": "claimed",
            "raster_layer_defs": {
                "raster": {"src_filepath": raster_filepath},
            },
        })
        self.contract = {
            "validator": "raster",
            "checks": ({
                "source_type": "raster",
                "mask": "test",
                "layers": ("raster",),
            },),
        }

    def test_raster_overlaps_actual_aoi_mask_pixels(self):
        self.prepare_raster_mask_case(80, 20)

        status = self.run_validation()

        self.assertEqual("ok", status.status)
        self.assertEqual(("raster",), status.params["_aoi_validated_media"])

    def test_raster_inside_mask_extent_but_outside_aoi_pixels_aborts(self):
        self.prepare_raster_mask_case(0, 100)

        status = self.run_validation()

        self.assertEqual("aborted", status.status)
        self.assertIsNone(status.status_properties["aoi_code"])
        self.assertIn("does not overlap", status.messages[0])

    def test_invalid_vector_boundary_is_repaired_for_validation(self):
        from osgeo import ogr
        from osgeo import osr

        boundary_filepath = self.params["boundary_dir"].joinpath(
            "vector", "invalid_boundary.gpkg"
        )
        datasource = ogr.GetDriverByName("GPKG").CreateDataSource(
            str(boundary_filepath)
        )
        spatial_reference = osr.SpatialReference()
        spatial_reference.ImportFromEPSG(3035)
        spatial_reference.SetAxisMappingStrategy(
            osr.OAMS_TRADITIONAL_GIS_ORDER
        )
        layer = datasource.CreateLayer(
            "boundary", spatial_reference, ogr.wkbPolygon
        )
        layer.CreateField(ogr.FieldDefn("FUA_CODE", ogr.OFTString))
        feature = ogr.Feature(layer.GetLayerDefn())
        feature.SetField("FUA_CODE", "claimed")
        feature.SetGeometry(ogr.CreateGeometryFromWkt(
            "POLYGON((0 100, 100 0, 100 100, 0 0, 0 100))"
        ))
        layer.CreateFeature(feature)
        feature = None
        datasource = None

        raster_filepath = self.jobdir_manager.tmp_dir.joinpath(
            "invalid-boundary-raster.tif"
        )
        RasterCheckTestCase.create_raster(
            raster_filepath,
            numpy.ones((10, 10), dtype=numpy.uint8),
            10,
            ulx=0,
            uly=100,
        )
        self.params.update({
            "aoi_code": "claimed",
            "raster_layer_defs": {
                "raster": {"src_filepath": raster_filepath},
            },
        })
        self.contract = {
            "validator": "raster",
            "checks": ({
                "source_type": "vector",
                "source": boundary_filepath.name,
                "code_field": "fua_code",
                "layers": ("raster",),
            },),
        }

        status = self.run_validation()

        self.assertEqual("ok", status.status)
        self.assertEqual("claimed", status.status_properties["aoi_code"])
