#!/usr/bin/env python3


from unittest import TestCase

import osgeo.ogr as ogr
from osgeo.gdalconst import GA_ReadOnly

from qc_tool.common import QCException
from qc_tool.test.helper import VectorCheckTestCase


class TestValidateSkipSteps(TestCase):
    def setUp(self):
        self.product_definition = {"steps": [{"required": True}, {"required": False}]}

    def test(self):
        from qc_tool.worker.dispatch import validate_skip_steps
        validate_skip_steps([2], self.product_definition)

    def test_out_of_range(self):
        from qc_tool.worker.dispatch import validate_skip_steps
        self.assertRaisesRegex(QCException, "Skip step 3 is out of range.", validate_skip_steps, [3], self.product_definition)
        self.assertRaisesRegex(QCException, "Skip step 0 is out of range.", validate_skip_steps, [0], self.product_definition)

    def test_duplicit(self):
        from qc_tool.worker.dispatch import validate_skip_steps
        self.assertRaisesRegex(QCException, "Duplicit skip step 2.", validate_skip_steps, [2, 2], self.product_definition)

    def test_required(self):
        from qc_tool.worker.dispatch import validate_skip_steps
        self.assertRaisesRegex(QCException, "Required step 1 can not be skipped.", validate_skip_steps, [1], self.product_definition)


class Test_dump_error_table(VectorCheckTestCase):
    def test(self):
        from qc_tool.worker.dispatch import dump_error_table
        cursor = self.params["connection_manager"].get_connection().cursor()

        # Create a source layer.
        cursor.execute("CREATE TABLE pg_table (fid integer, attr1 char(1), geom geometry(Polygon, 3035));")
        cursor.execute("INSERT INTO pg_table VALUES (1, 'a', ST_MakeEnvelope(0, 0, 1, 1, 3035)),"
                                                  " (2, 'b', ST_MakeEnvelope(2, 0, 3, 1, 3035));")

        # Create an error table.
        cursor.execute("CREATE TABLE error_table (fid integer);")
        cursor.execute("INSERT INTO error_table VALUES (1), (2), (3);")
        output_dir = self.params["jobdir_manager"].output_dir

        # Export into geopackage.
        filename = dump_error_table(self.params["connection_manager"], "error_table", "pg_table", "fid", output_dir)
        filepath = output_dir.joinpath("pg_table.gpkg")
        self.assertEqual(filepath.name, filename)
        self.assertTrue(filepath.is_file())

        # Validate the exported geopackage.
        dsrc = ogr.Open(str(filepath), GA_ReadOnly)
        self.assertEqual(1, dsrc.GetLayerCount())
        self.assertEqual("pg_table", dsrc.GetLayerByIndex(0).GetName())
        self.assertEqual(2, dsrc.GetLayerByIndex(0).GetFeatureCount())
        self.assertEqual("EPSG", dsrc.GetLayerByIndex(0).GetSpatialRef().GetAuthorityName(None))
        self.assertEqual("3035", dsrc.GetLayerByIndex(0).GetSpatialRef().GetAuthorityCode(None))


class Test_dump_full_table(VectorCheckTestCase):
    def test(self):
        from qc_tool.worker.dispatch import dump_full_table
        cursor = self.params["connection_manager"].get_connection().cursor()

        # Create a layer to be exported.
        cursor.execute("CREATE TABLE pg_table (fid integer, attr1 char(1), geom geometry(Polygon, 3035));")
        cursor.execute("INSERT INTO pg_table VALUES (1, 'a', ST_MakeEnvelope(0, 0, 1, 1, 3035)),"
                                                  " (2, 'b', ST_MakeEnvelope(2, 0, 3, 1, 3035));")
        output_dir = self.params["jobdir_manager"].output_dir

        # Export into geopackage.
        filename = dump_full_table(self.params["connection_manager"], "pg_table", output_dir)
        filepath = output_dir.joinpath("pg_table.gpkg")
        self.assertEqual(filepath.name, filename)
        self.assertTrue(filepath.is_file())

        # Validate the exported geopackage.
        dsrc = ogr.Open(str(filepath), GA_ReadOnly)
        self.assertEqual(1, dsrc.GetLayerCount())
        self.assertEqual("pg_table", dsrc.GetLayerByIndex(0).GetName())
        self.assertEqual(2, dsrc.GetLayerByIndex(0).GetFeatureCount())
        self.assertEqual("EPSG", dsrc.GetLayerByIndex(0).GetSpatialRef().GetAuthorityName(None))
        self.assertEqual("3035", dsrc.GetLayerByIndex(0).GetSpatialRef().GetAuthorityCode(None))
