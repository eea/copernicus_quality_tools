#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import numpy

from qc_tool.test.helper import RasterCheckTestCase
from qc_tool.test.helper import VectorCheckTestCase


class TestVectorAoi(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.cursor = self.params["connection_manager"].get_connection().cursor()
        self.addCleanup(self.cursor.close)
        self.cursor.execute(
            "CREATE TABLE reference (fid integer, geom geometry(Polygon, 4326));"
        )
        self.cursor.execute(
            'CREATE TABLE boundary ("FUA_CODE" text, geom geometry(Polygon, 4326));'
        )
        self.params.update({
            "aoi_code": "mt",
            "layer_defs": {
                "reference": {"pg_layer_name": "reference"},
                "boundary": {"pg_layer_name": "boundary"},
            },
        })
        self.contract = {
            "validator": "vector",
            "source_type": "vector",
            "source": "boundary.gpkg",
            "code_field": "FUA_CODE",
            "layers": ("reference",),
        }

    def run_validation(self):
        from qc_tool.vector.aoi import validate_aoi

        status = self.status_class()
        validate_aoi(self.params, status, self.contract)
        return status

    def assert_valid(self, status, expected="mt"):
        self.assertEqual("ok", status.status)
        self.assertEqual(expected, status.status_properties["aoi_code"])
        self.assertEqual(("vector",), status.params["_aoi_validated_media"])

    def assert_invalid(self, status):
        self.assertEqual("aborted", status.status)
        self.assertIsNone(status.params["aoi_code"])
        self.assertIsNone(status.status_properties["aoi_code"])
        self.assertEqual((), status.params["_aoi_validated_media"])

    def test_matching_aoi(self):
        self.cursor.execute(
            "INSERT INTO reference VALUES "
            "(1, ST_MakeEnvelope(0.2, 0.2, 0.8, 0.8, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO boundary VALUES "
            "('MT', ST_MakeEnvelope(0, 0, 1, 1, 4326));"
        )

        self.assert_valid(self.run_validation())

    def test_equivalent_boundary_features_resolve_to_one_aoi(self):
        self.params["aoi_code"] = "EE003L1"
        self.cursor.execute(
            "INSERT INTO reference VALUES "
            "(1, ST_MakeEnvelope(0, 0, 2, 1, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO boundary VALUES "
            "('EE003L0', ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
            "('ee003l', ST_MakeEnvelope(1, 0, 2, 1, 4326));"
        )

        self.assert_valid(self.run_validation(), "ee003l")

    def test_overlapping_official_aois_do_not_create_a_second_job_aoi(self):
        self.cursor.execute(
            "INSERT INTO reference VALUES "
            "(1, ST_MakeEnvelope(0, 0, 2, 1, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO boundary VALUES "
            "('MT', ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
            "('CZ', ST_MakeEnvelope(1, 0, 2, 1, 4326));"
        )

        self.assert_valid(self.run_validation())

    def test_mismatching_spatial_aoi_aborts(self):
        self.cursor.execute(
            "INSERT INTO reference VALUES "
            "(1, ST_MakeEnvelope(0.2, 0.2, 0.8, 0.8, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO boundary VALUES "
            "('CZ', ST_MakeEnvelope(0, 0, 1, 1, 4326));"
        )

        status = self.run_validation()

        self.assert_invalid(status)
        self.assertIn("is not present", status.messages[0])

    def test_boundary_touch_does_not_count_as_polygon_overlap(self):
        self.cursor.execute(
            "INSERT INTO reference VALUES "
            "(1, ST_MakeEnvelope(1, 0, 2, 1, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO boundary VALUES "
            "('MT', ST_MakeEnvelope(0, 0, 1, 1, 4326));"
        )

        status = self.run_validation()

        self.assert_invalid(status)
        self.assertIn("does not overlap", status.messages[0])

    def test_invalid_source_geometry_can_still_be_located(self):
        self.cursor.execute(
            "INSERT INTO reference VALUES "
            "(1, ST_GeomFromText("
            "'POLYGON((0.1 0.1, 0.9 0.9, 0.9 0.1, "
            "0.1 0.9, 0.1 0.1))', 4326));"
        )
        self.cursor.execute(
            "INSERT INTO boundary VALUES "
            "('MT', ST_MakeEnvelope(0, 0, 1, 1, 4326));"
        )

        self.assert_valid(self.run_validation())

    def test_invalid_boundary_geometry_is_repaired_for_validation(self):
        self.cursor.execute(
            "INSERT INTO reference VALUES "
            "(1, ST_MakeEnvelope(0, 0, 1, 1, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO boundary VALUES "
            "('MT', ST_GeomFromText("
            "'POLYGON((0.1 0.1, 0.9 0.9, 0.9 0.1, "
            "0.1 0.9, 0.1 0.1))', 4326));"
        )

        self.assert_valid(self.run_validation())

    def test_differing_coordinate_systems_are_transformed(self):
        self.cursor.execute("DROP TABLE boundary;")
        self.cursor.execute(
            'CREATE TABLE boundary ("FUA_CODE" text, '
            "geom geometry(Polygon, 3857));"
        )
        self.cursor.execute(
            "INSERT INTO reference VALUES "
            "(1, ST_MakeEnvelope(0.1, 0.1, 0.2, 0.2, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO boundary VALUES "
            "('MT', ST_MakeEnvelope(10000, 10000, 25000, 25000, 3857));"
        )

        self.assert_valid(self.run_validation())

    def test_selected_per_aoi_boundary_needs_no_code_field(self):
        self.cursor.execute("DROP TABLE boundary;")
        self.cursor.execute(
            "CREATE TABLE boundary (geom geometry(Polygon, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO reference VALUES "
            "(1, ST_MakeEnvelope(0.2, 0.2, 0.8, 0.8, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO boundary VALUES "
            "(ST_MakeEnvelope(0, 0, 1, 1, 4326));"
        )
        self.contract.update({
            "source": "boundary_clc_{aoi_code}.gpkg",
            "code_field": None,
        })

        self.assert_valid(self.run_validation())

    def test_selected_product_boundary_ignores_unrelated_code_field(self):
        self.cursor.execute(
            "INSERT INTO reference VALUES "
            "(1, ST_MakeEnvelope(0.2, 0.2, 0.8, 0.8, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO boundary VALUES "
            "('4', ST_MakeEnvelope(0, 0, 1, 1, 4326));"
        )
        self.params["aoi_code"] = "DU001"
        self.contract.update({
            "code_field": None,
            "selected_boundary": True,
        })

        self.assert_valid(self.run_validation(), "du001")

    def test_empty_vector_medium_is_not_applicable_after_raster_validation(self):
        self.params.update({
            "skip_vector_checks": True,
            "_aoi_validated_media": ("raster",),
            "aoi_validation_plan": {
                "media": ("raster", "vector"),
            },
        })

        status = self.run_validation()

        self.assertEqual("ok", status.status)
        self.assertEqual("mt", status.status_properties["aoi_code"])
        self.assertEqual(("raster",), status.params["_aoi_validated_media"])
        self.assertEqual(
            ("vector",), status.params["_aoi_not_applicable_media"]
        )

    def prepare_raster_mask_contract(self, source_geometry):
        self.cursor.execute("DROP TABLE reference;")
        self.cursor.execute(
            "CREATE TABLE reference (fid integer, "
            "geom geometry(Polygon, 3035));"
        )
        self.cursor.execute(
            "INSERT INTO reference VALUES (1, ST_GeomFromText(%s, 3035));",
            (source_geometry,),
        )

        boundary_directory = self.params["jobdir_manager"].tmp_dir.joinpath(
            "boundaries", "raster"
        )
        mask_values = numpy.zeros((10, 10), dtype=numpy.uint8)
        mask_values[8:10, 8:10] = 1
        mask_filepath = boundary_directory.joinpath(
            "mask_test_010m_claimed.tif"
        )
        RasterCheckTestCase.create_raster(
            mask_filepath, mask_values, 10, ulx=0, uly=100
        )
        raster_filepath = self.params["jobdir_manager"].tmp_dir.joinpath(
            "delivery-raster.tif"
        )
        RasterCheckTestCase.create_raster(
            raster_filepath,
            numpy.ones((1, 1), dtype=numpy.uint8),
            10,
            ulx=1000,
            uly=1000,
        )
        self.params.update({
            "aoi_code": "claimed",
            "boundary_dir": boundary_directory.parent,
            "raster_layer_defs": {
                "raster": {"src_filepath": raster_filepath},
            },
        })
        self.contract = {
            "validator": "vector",
            "source_type": "raster",
            "checks": ({
                "source_type": "raster",
                "mask": "test",
                "layers": ("raster",),
            },),
            "layers": ("reference",),
        }

    def test_vector_overlaps_actual_aoi_mask_pixels(self):
        self.prepare_raster_mask_contract(
            "POLYGON((80 0, 100 0, 100 20, 80 20, 80 0))"
        )

        self.assert_valid(self.run_validation(), "claimed")

    def test_vector_inside_mask_extent_but_outside_aoi_pixels_aborts(self):
        self.prepare_raster_mask_contract(
            "POLYGON((0 80, 20 80, 20 100, 0 100, 0 80))"
        )

        status = self.run_validation()

        self.assert_invalid(status)
        self.assertIn("does not overlap", status.messages[0])
