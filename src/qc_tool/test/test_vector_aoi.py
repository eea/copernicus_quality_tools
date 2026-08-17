#!/usr/bin/env python3
# -*- coding: utf-8 -*-


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
            "CREATE TABLE boundary (aoi_code text, geom geometry(Polygon, 4326));"
        )
        self.params.update({
            "aoi_code": "mt",
            "layer_defs": {
                "reference": {"pg_layer_name": "reference"},
                "boundary": {"pg_layer_name": "boundary"},
            },
            "layers": ["reference"],
        })

    def run_check(self):
        from qc_tool.vector.aoi import run_check

        status = self.status_class()
        run_check(self.params, status)
        return status

    def assert_valid(self, status, expected="mt"):
        self.assertEqual("ok", status.status)
        self.assertEqual(expected, status.params["aoi_code"])
        self.assertEqual(expected, status.status_properties["aoi_code"])
        self.assertTrue(status.params["_aoi_spatially_validated"])

    def assert_invalid(self, status):
        self.assertEqual("aborted", status.status)
        self.assertIsNone(status.params["aoi_code"])
        self.assertIsNone(status.status_properties["aoi_code"])
        self.assertFalse(status.params["_aoi_spatially_validated"])

    def test_matching_aoi(self):
        self.cursor.execute(
            "INSERT INTO reference VALUES (1, ST_MakeEnvelope(0.2, 0.2, 0.8, 0.8, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO boundary VALUES ('MT', ST_MakeEnvelope(0, 0, 1, 1, 4326));"
        )

        self.assert_valid(self.run_check())

    def test_duplicate_boundary_features_with_same_code_are_one_aoi(self):
        self.cursor.execute(
            "INSERT INTO reference VALUES (1, ST_MakeEnvelope(0, 0, 2, 1, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO boundary VALUES"
            " ('MT', ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
            " ('mt', ST_MakeEnvelope(1, 0, 2, 1, 4326));"
        )

        self.assert_valid(self.run_check())

    def test_multiple_spatial_aoi_codes_abort(self):
        self.cursor.execute(
            "INSERT INTO reference VALUES (1, ST_MakeEnvelope(0, 0, 2, 1, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO boundary VALUES"
            " ('MT', ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
            " ('CZ', ST_MakeEnvelope(1, 0, 2, 1, 4326));"
        )

        status = self.run_check()

        self.assert_invalid(status)
        self.assertIn("multiple AOI codes: cz, mt", status.messages[0])

    def test_mismatching_spatial_aoi_aborts(self):
        self.cursor.execute(
            "INSERT INTO reference VALUES (1, ST_MakeEnvelope(0.2, 0.2, 0.8, 0.8, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO boundary VALUES ('CZ', ST_MakeEnvelope(0, 0, 1, 1, 4326));"
        )

        status = self.run_check()

        self.assert_invalid(status)
        self.assertIn("does not match the spatially detected AOI code 'cz'", status.messages[0])

    def test_polygon_boundary_touch_does_not_count_as_overlap(self):
        self.cursor.execute(
            "INSERT INTO reference VALUES (1, ST_MakeEnvelope(1, 0, 2, 1, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO boundary VALUES ('MT', ST_MakeEnvelope(0, 0, 1, 1, 4326));"
        )

        status = self.run_check()

        self.assert_invalid(status)
        self.assertIn("does not overlap", status.messages[0])

    def test_no_spatial_overlap_aborts(self):
        self.cursor.execute(
            "INSERT INTO reference VALUES (1, ST_MakeEnvelope(2, 2, 3, 3, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO boundary VALUES ('MT', ST_MakeEnvelope(0, 0, 1, 1, 4326));"
        )

        status = self.run_check()

        self.assert_invalid(status)
        self.assertIn("does not overlap", status.messages[0])

    def test_selected_boundary_without_code_field_uses_claimed_aoi(self):
        self.params["aoi_code"] = "MT"
        self.params["aoi_boundary_source"] = "clc/boundary_clc_{aoi_code}.gpkg"
        self.cursor.execute(
            "INSERT INTO reference VALUES (1, ST_MakeEnvelope(0.2, 0.2, 0.8, 0.8, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO boundary VALUES (NULL, ST_MakeEnvelope(0, 0, 1, 1, 4326));"
        )

        self.assert_valid(self.run_check())

    def test_existing_boundary_source_key_enables_selected_boundary_mode(self):
        self.params["boundary_source"] = "clc/boundary_clc_{aoi_code}.shp"
        self.cursor.execute("DROP TABLE boundary;")
        self.cursor.execute(
            "CREATE TABLE boundary (geom geometry(Polygon, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO reference VALUES (1, ST_MakeEnvelope(0.2, 0.2, 0.8, 0.8, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO boundary VALUES (ST_MakeEnvelope(0, 0, 1, 1, 4326));"
        )

        self.assert_valid(self.run_check())

    def test_fixed_boundary_without_recognized_code_field_aborts(self):
        self.cursor.execute("DROP TABLE boundary;")
        self.cursor.execute(
            "CREATE TABLE boundary (region text, geom geometry(Polygon, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO reference VALUES (1, ST_MakeEnvelope(0.2, 0.2, 0.8, 0.8, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO boundary VALUES ('MT', ST_MakeEnvelope(0, 0, 1, 1, 4326));"
        )

        status = self.run_check()

        self.assert_invalid(status)
        self.assertIn("has no recognized AOI code field", status.messages[0])

    def test_pattern_normalizes_claimed_and_boundary_codes(self):
        self.params["aoi_code"] = "EE003L1"
        self.params["aoi_code_pattern"] = r"^(?P<aoi_code>[a-z]{2}[0-9]{3}l)"
        self.cursor.execute(
            "INSERT INTO reference VALUES (1, ST_MakeEnvelope(0.2, 0.2, 0.8, 0.8, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO boundary VALUES ('EE003L0', ST_MakeEnvelope(0, 0, 1, 1, 4326));"
        )

        self.assert_valid(self.run_check(), "ee003l")

    def test_standard_ua_codes_are_normalized_without_configuration(self):
        self.cursor.execute("DROP TABLE boundary;")
        self.cursor.execute(
            'CREATE TABLE boundary ("FUA_CODE" text, geom geometry(Polygon, 4326));'
        )
        self.params["aoi_code"] = "EE003L1"
        self.cursor.execute(
            "INSERT INTO reference VALUES (1, ST_MakeEnvelope(0.2, 0.2, 0.8, 0.8, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO boundary VALUES ('EE003L0', ST_MakeEnvelope(0, 0, 1, 1, 4326));"
        )

        self.assert_valid(self.run_check(), "ee003l")

    def test_standard_rpz_codes_are_normalized_without_configuration(self):
        self.params["aoi_code"] = "DU007"
        self.cursor.execute(
            "INSERT INTO reference VALUES (1, ST_MakeEnvelope(0.2, 0.2, 0.8, 0.8, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO boundary VALUES ('DU007T', ST_MakeEnvelope(0, 0, 1, 1, 4326));"
        )

        self.assert_valid(self.run_check(), "du007")

    def test_multiple_discoverable_code_fields_abort(self):
        self.cursor.execute("DROP TABLE boundary;")
        self.cursor.execute(
            "CREATE TABLE boundary (aoi_code text, du_id text, geom geometry(Polygon, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO reference VALUES (1, ST_MakeEnvelope(0.2, 0.2, 0.8, 0.8, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO boundary VALUES ('MT', 'MT', ST_MakeEnvelope(0, 0, 1, 1, 4326));"
        )

        status = self.run_check()

        self.assert_invalid(status)
        self.assertIn("multiple recognized AOI code fields", status.messages[0])

    def test_explicit_code_field_overrides_discovery(self):
        self.cursor.execute("DROP TABLE boundary;")
        self.cursor.execute(
            "CREATE TABLE boundary (aoi_code text, du_id text, geom geometry(Polygon, 4326));"
        )
        self.params["aoi_boundary_code_field"] = "aoi_code"
        self.cursor.execute(
            "INSERT INTO reference VALUES (1, ST_MakeEnvelope(0.2, 0.2, 0.8, 0.8, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO boundary VALUES ('MT', 'CZ', ST_MakeEnvelope(0, 0, 1, 1, 4326));"
        )

        self.assert_valid(self.run_check())

    def test_differing_source_and_boundary_srids_are_transformed(self):
        self.cursor.execute("DROP TABLE boundary;")
        self.cursor.execute(
            "CREATE TABLE boundary (aoi_code text, geom geometry(Polygon, 3857));"
        )
        self.cursor.execute(
            "INSERT INTO reference VALUES (1, ST_MakeEnvelope(0.1, 0.1, 0.2, 0.2, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO boundary VALUES ('MT', ST_MakeEnvelope(10000, 10000, 25000, 25000, 3857));"
        )

        self.assert_valid(self.run_check())

    def test_line_overlap_uses_positive_length(self):
        self.cursor.execute("DROP TABLE reference;")
        self.cursor.execute(
            "CREATE TABLE reference (fid integer, geom geometry(LineString, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO reference VALUES (1, ST_GeomFromText('LINESTRING(-1 0.5, 2 0.5)', 4326));"
        )
        self.cursor.execute(
            "INSERT INTO boundary VALUES ('MT', ST_MakeEnvelope(0, 0, 1, 1, 4326));"
        )

        self.assert_valid(self.run_check())

    def test_point_intersection_counts_as_spatial_overlap(self):
        self.cursor.execute("DROP TABLE reference;")
        self.cursor.execute(
            "CREATE TABLE reference (fid integer, geom geometry(Point, 4326));"
        )
        self.cursor.execute(
            "INSERT INTO reference VALUES (1, ST_SetSRID(ST_MakePoint(0.5, 0.5), 4326));"
        )
        self.cursor.execute(
            "INSERT INTO boundary VALUES ('MT', ST_MakeEnvelope(0, 0, 1, 1, 4326));"
        )

        self.assert_valid(self.run_check())
