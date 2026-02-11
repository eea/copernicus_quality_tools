#!/usr/bin/env python3


from unittest import expectedFailure
from unittest import skipIf

from osgeo import gdal
from osgeo import osr
import numpy as np

from qc_tool.common import CONFIG
from qc_tool.common import TEST_DATA_DIR
from qc_tool.test.helper import VectorCheckTestCase


class Test_unzip(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.params["tmp_dir"] = self.params["jobdir_manager"].tmp_dir

    def test_shp(self):
        from qc_tool.vector.unzip import run_check
        self.params["filepath"] = TEST_DATA_DIR.joinpath("vector", "rpz", "rpz_LCLU2012_DU007T.zip")
        status = self.status_class()
        run_check(self.params, status)
        self.assertIn("unzip_dir", status.params)
        self.assertEqual("ok", status.status)
        unzip_dir = status.params["unzip_dir"]
        unzipped_file_names = [path.name for path in unzip_dir.glob("**/*") if path.is_file()]
        self.assertIn("rpz_DU007T_lclu2012_v01.shp", unzipped_file_names)

    def test_gpkg(self):
        from qc_tool.vector.unzip import run_check
        self.params["filepath"] = TEST_DATA_DIR.joinpath("vector", "ua", "gpkg", "EE003L1_NARVA_UA2012.gpkg.zip")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.assertIn("unzip_dir", status.params)
        unzip_dir = status.params["unzip_dir"]
        unzipped_file_names = [path.name for path in unzip_dir.glob("**/*") if path.is_file()]
        self.assertIn("EE003L1_NARVA_UA2012.gpkg", unzipped_file_names)

    def test_gdb(self):
        from qc_tool.vector.unzip import run_check
        self.params["filepath"] = TEST_DATA_DIR.joinpath("vector", "ua", "gdb", "EE003L1_NARVA_UA2012.gdb.zip")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.assertIn("unzip_dir", status.params)
        unzip_dir = status.params["unzip_dir"]
        unzipped_subdir_names = [path.name for path in unzip_dir.glob("**") if path.is_dir()]
        self.assertIn("EE003L1_NARVA_UA2012.gdb", unzipped_subdir_names)

    def test_invalid_extension(self):
        from qc_tool.vector.unzip import run_check
        self.params["filepath"] = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.xml")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status)
        self.assertIn("Delivery must be a .zip file.", status.messages[0])

    def test_invalid_file(self):
        from qc_tool.vector.unzip import run_check
        self.params["filepath"] = TEST_DATA_DIR.joinpath("non_existent_zip_file.zip")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status, "Unzipping a non-existent v_unzip should be aborted.")


class Test_naming_rpz(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        from qc_tool.vector.unzip import run_check as unzip_check
        self.params.update({"tmp_dir": self.params["jobdir_manager"].tmp_dir,
                            "filepath": TEST_DATA_DIR.joinpath("vector", "rpz", "rpz_LCLU2012_DU007T.zip"),
                            "boundary_dir": TEST_DATA_DIR.joinpath("boundaries")})
        status = self.status_class()
        unzip_check(self.params, status)
        self.params["unzip_dir"] = status.params["unzip_dir"]

    def test(self):
        from qc_tool.vector.naming import run_check
        self.params.update({"layer_names": {"rpz": "^rpz_du(?P<aoi_code>[0-9]{3})[a-z]_lclu2012_v[0-9]{2}$"},
                            "formats": [".shp"],
                            "aoi_codes": ["007"],
                            "boundary_source": "boundary_rpz.shp",
                            "reference_year": "2012"})
        status = self.status_class()
        run_check(self.params, status)

        self.assertEqual("ok", status.status)
        self.assertEqual("rpz_DU007T_lclu2012_v01.shp", status.params["layer_defs"]["rpz"]["src_filepath"].name)
        self.assertEqual("rpz_DU007T_lclu2012_v01", status.params["layer_defs"]["rpz"]["src_layer_name"])
        self.assertEqual("boundary_rpz.shp", status.params["layer_defs"]["boundary"]["src_filepath"].name)
        self.assertEqual("boundary_rpz", status.params["layer_defs"]["boundary"]["src_layer_name"])
        self.assertIn("reference_year", status.status_properties)
        self.assertEqual("2012", status.status_properties["reference_year"])


class Test_naming_n2k(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        from qc_tool.vector.unzip import run_check as unzip_check
        self.params.update({"tmp_dir": self.params["jobdir_manager"].tmp_dir,
                            "filepath": TEST_DATA_DIR.joinpath("vector", "n2k", "n2k_example_cz_correct.zip"),
                            "formats": [".shp"],
                            "layer_names": {"n2k": "^n2k_du[0-9]{3}[a-z]_lclu_v[0-9]+_[0-9]{8}$"},
                            "boundary_source": "boundary_n2k.shp",
                            "boundary_dir": TEST_DATA_DIR.joinpath("boundaries")})
        status = self.status_class()
        unzip_check(self.params, status)
        self.params["unzip_dir"] = status.params["unzip_dir"]

    def test(self):
        from qc_tool.vector.naming import run_check
        status = self.status_class()
        run_check(self.params, status)

        self.assertEqual("ok", status.status)
        self.assertEqual("n2k_du001z_lclu_v99_20190108.shp", status.params["layer_defs"]["n2k"]["src_filepath"].name)
        self.assertEqual("n2k_du001z_lclu_v99_20190108", status.params["layer_defs"]["n2k"]["src_layer_name"])
        self.assertEqual("boundary_n2k.shp", status.params["layer_defs"]["boundary"]["src_filepath"].name)
        self.assertEqual("boundary_n2k", status.params["layer_defs"]["boundary"]["src_layer_name"])

    def test_reference_year(self):
        from qc_tool.vector.naming import run_check

        self.params.update({"reference_year": "2019"})
        status = self.status_class()
        run_check(self.params, status)

        self.assertEqual("ok", status.status)
        self.assertIn("reference_year", status.status_properties)
        self.assertEqual("2019", status.status_properties["reference_year"])

    def test_bad_layer_name_aborts(self):
        from qc_tool.vector.naming import run_check

        # Rename layer to bad one.
        src_gdb_filepath = self.params["unzip_dir"].joinpath("n2k_du001z_lclu_v99_20170108", "n2k_du001z_lclu_v99_20190108.shp")
        dst_gdb_filepath = src_gdb_filepath.with_name("Xn2k_du001z_lclu_v99_20190108.shp")
        src_gdb_filepath.rename(dst_gdb_filepath)

        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status)


class Test_naming_clc(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.params.update({"unzip_dir": TEST_DATA_DIR.joinpath("vector", "clc"),
                            "aoi_codes": ["cz", "sk", "mt"],
                            "reference_year": "2012",
                            "formats": [".gdb"],
                            "gdb_filename_regex": "^clc2012_(?P<aoi_code>.+).gdb$",
                            "layer_names": {
                                "reference": "^clc12_(?P<aoi_code>.+)$",
                                "initial": "^clc06_(?P<aoi_code>.+)$",
                                "change": "^cha12_(?P<aoi_code>.+)$",
                            },
                            "boundary_source": "clc/boundary_clc_{aoi_code}.shp",
                            "boundary_dir": TEST_DATA_DIR.joinpath("boundaries")})

    def test(self):
        from qc_tool.vector.naming import run_check
        status = self.status_class()
        run_check(self.params, status)

        self.assertEqual("ok", status.status)
        self.assertEqual(4, len(status.params["layer_defs"]))
        self.assertEqual("clc2012_mt.gdb", status.params["layer_defs"]["reference"]["src_filepath"].name)
        self.assertEqual("clc12_MT", status.params["layer_defs"]["reference"]["src_layer_name"])
        self.assertEqual("clc2012_mt.gdb", status.params["layer_defs"]["initial"]["src_filepath"].name)
        self.assertEqual("clc06_MT", status.params["layer_defs"]["initial"]["src_layer_name"])
        self.assertEqual("clc2012_mt.gdb", status.params["layer_defs"]["change"]["src_filepath"].name)
        self.assertEqual("cha12_MT", status.params["layer_defs"]["change"]["src_layer_name"])
        self.assertEqual("boundary_clc_mt.shp", status.params["layer_defs"]["boundary"]["src_filepath"].name)
        self.assertEqual("boundary_clc_mt", status.params["layer_defs"]["boundary"]["src_layer_name"])
        self.assertIn("reference_year", status.status_properties)
        self.assertEqual("2012", status.status_properties["reference_year"])

    def test_mismatched_regex_aborts(self):
        from qc_tool.vector.naming import run_check
        self.params["layer_names"]["initial"] = "^{country_code:s}/xxx_{country_code:s}$"
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status)


class Test_naming_ua_gdb(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        from qc_tool.vector.unzip import run_check as unzip_check
        self.params.update({"tmp_dir": self.params["jobdir_manager"].tmp_dir,
                            "filepath": TEST_DATA_DIR.joinpath("vector", "ua", "gdb", "EE003L1_NARVA_UA2012.gdb.zip")})
        status = self.status_class()
        unzip_check(self.params, status)
        self.params["unzip_dir"] = status.params["unzip_dir"]
        self.params.update({"reference_year": "2012",
                            "formats": [".gdb"],
                            "gdb_filename_regex": "^[a-z0-9]{7}_.*$",
                            "layer_names": {
                                "reference": "_ua2012$"}
                            })


    def test(self):
        from qc_tool.vector.naming import run_check
        status = self.status_class()
        run_check(self.params, status)

        self.assertEqual("ok", status.status)
        self.assertEqual(1, len(status.params["layer_defs"]))
        self.assertEqual("EE003L1_NARVA_UA2012.gdb", status.params["layer_defs"]["reference"]["src_filepath"].name)
        self.assertEqual("EE003L1_NARVA_UA2012", status.params["layer_defs"]["reference"]["src_layer_name"])
        self.assertIn("reference_year", status.status_properties)
        self.assertEqual("2012", status.status_properties["reference_year"])


    def test_bad_gdb_filename_aborts(self):
        from qc_tool.vector.naming import run_check

        # Rename gdb filename to bad one.
        src_gdb_filepath = self.params["unzip_dir"].joinpath("EE003L1_NARVA_UA2012.gdb")
        dst_gdb_filepath = src_gdb_filepath.with_name("XEE003L1_NARVA_UA2012")
        src_gdb_filepath.rename(dst_gdb_filepath)

        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status)

    def test_missing_layer_aborts(self):
        from qc_tool.vector.naming import run_check
        self.params["layer_names"]["reference"] = "non-existing-layer-name"
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status)


class Test_naming_ua_gpkg(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        from qc_tool.vector.unzip import run_check as unzip_check

        self.params.update({"tmp_dir": self.params["jobdir_manager"].tmp_dir,
                            "filepath": TEST_DATA_DIR.joinpath("vector", "ua", "gpkg", "EE003L1_NARVA_UA2012.gpkg.zip")})
        status = self.status_class()
        unzip_check(self.params, status)

        self.params["unzip_dir"] = status.params["unzip_dir"]
        self.params.update({"layer_names": {"reference": "_ua2012$"},
                            "reference_year": "2012",
                            "formats": [".gpkg"],
                            "documents": {}})

    def test(self):
        from qc_tool.vector.naming import run_check
        status = self.status_class()
        run_check(self.params, status)

        self.assertEqual("ok", status.status)
        self.assertEqual(1, len(status.params["layer_defs"]))
        self.assertEqual("EE003L1_NARVA_UA2012.gpkg", status.params["layer_defs"]["reference"]["src_filepath"].name)
        self.assertEqual("EE003L1_NARVA_UA2012", status.params["layer_defs"]["reference"]["src_layer_name"])
        self.assertIn("reference_year", status.status_properties)
        self.assertEqual("2012", status.status_properties["reference_year"])

    def test_found_document(self):
        from qc_tool.vector.naming import run_check
        self.params["documents"] = {"map.pdf": "_map.pdf$",
                                    "delivery_report.pdf": "_delivery_report.pdf$"}
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_missing_document(self):
        from qc_tool.vector.naming import run_check
        self.params["documents"] = {"extra_pdf_document": "_extra_pdf_document.pdf$"}
        status = self.status_class()
        run_check(self.params, status)
        self.assertIn("Warning: the delivery does not contain expected document 'extra_pdf_document'.", status.messages[0])


class Test_attribute(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        gdb_dir = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb")
        self.params.update({"layer_defs": {"layer_0": {"src_filepath": gdb_dir,
                                                       "src_layer_name": "clc12_mt"}},
                            "layers": ["layer_0"],
                            "required": {"id": "string",
                                         "code_12": "string",
                                         "area_ha": "real",
                                         "remark": "string"},
                            "ignored": ["shape_length", "shape_area"]})

    def test(self):
        from qc_tool.vector.attribute import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_ignored_attribute_ok(self):
        from qc_tool.vector.attribute import run_check
        self.params["ignored"].append("custom_ignored_attribute")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_extra_attribute_fails(self):
        from qc_tool.vector.attribute import run_check
        del self.params["required"]["remark"]
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)

    def test_bad_type_aborts(self):
        from qc_tool.vector.attribute import run_check
        self.params["required"]["code_12"] = "integer"
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status)

    def test_missing_attribute_aborts(self):
        from qc_tool.vector.attribute import run_check
        self.params["required"].update({"missing_attribute": "string"})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status)


class Test_epsg_clc(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        gdb_dir = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb")
        boundary_path = TEST_DATA_DIR.joinpath("boundaries", "vector", "clc", "boundary_clc_mt.shp")
        self.params.update({"layer_defs": {"boundary": {"src_filepath": boundary_path,
                                                        "src_layer_name": boundary_path.stem},
                                           "layer_0": {"src_filepath": gdb_dir,
                                                       "src_layer_name": "clc06_mt"},
                                           "layer_1": {"src_filepath": gdb_dir,
                                                       "src_layer_name": "clc12_mt"}},
                            "layers": ["layer_0", "layer_1"]})

    def test(self):
        from qc_tool.vector.epsg_clc import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_missing_boundary_cancelled(self):
        from qc_tool.vector.epsg_clc import run_check
        del self.params["layer_defs"]["boundary"]
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("cancelled", status.status)


class Test_epsg_gdb(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        gdb_dir = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb")
        self.params.update({"layer_defs": {"layer_0": {"src_filepath": gdb_dir,
                                                       "src_layer_name": "clc06_mt"},
                                           "layer_1": {"src_filepath": gdb_dir,
                                                       "src_layer_name": "clc12_mt"}},
                            "layers": ["layer_0", "layer_1"],
                            "auto_identify_epsg": False,
                            "epsg": 23033})

    def test(self):
        from qc_tool.vector.epsg import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_mismatched_epsg_aborts(self):
        from qc_tool.vector.epsg import run_check
        self.params["epsg"] = 7777
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status)

class Test_epsg_gpkg(VectorCheckTestCase):
    def test(self):
        from qc_tool.vector.epsg import run_check
        gpkg_filepath = TEST_DATA_DIR.joinpath("vector", "ua", "gpkg", "EE003L1_NARVA_UA2012.gpkg")
        self.params.update({"layer_defs": {"reference": {"src_filepath": gpkg_filepath,
                                                         "src_layer_name": gpkg_filepath.stem}},
                            "layers": ["reference"],
                            "epsg": 3035,
                            "auto_identify_epsg": False})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)


class Test_epsg_auto_identify_epsg(VectorCheckTestCase):
    def test(self):
        from qc_tool.vector.epsg import run_check
        boundary_path = TEST_DATA_DIR.joinpath("boundaries", "vector", "boundary_n2k.shp")
        self.params.update({"layer_defs": {"boundary": {"src_filepath": boundary_path,
                                                        "src_layer_name": boundary_path.stem}},
                            "layers": ["boundary"],
                            "epsg": 3035,
                            "auto_identify_epsg": True})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)


class Test_import2pg(VectorCheckTestCase):
    def test(self):
        from qc_tool.vector.import2pg import run_check
        gdb_dir = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb")
        self.params.update({"layer_defs": {"layer_0": {"src_filepath": gdb_dir,
                                                       "src_layer_name": "clc06_mt",
                                                       "layer_alias": "layer_0"},
                                           "layer_1": {"src_filepath": gdb_dir,
                                                       "src_layer_name": "clc12_mt",
                                                       "layer_alias": "layer_1"}},
                            "layers": ["layer_0", "layer_1"]})
        status = self.status_class()
        run_check(self.params, status)
        print(status)

        self.assertEqual("ok", status.status)
        self.assertEqual("layer_0", self.params["layer_defs"]["layer_0"]["pg_layer_name"])
        self.assertEqual("objectid", self.params["layer_defs"]["layer_0"]["pg_fid_name"])
        self.assertEqual("layer_1", self.params["layer_defs"]["layer_1"]["pg_layer_name"])
        self.assertEqual("objectid", self.params["layer_defs"]["layer_1"]["pg_fid_name"])

        cur = self.params["connection_manager"].get_connection().cursor()
        cur.execute("""SELECT id FROM {:s};""".format(self.params["layer_defs"]["layer_0"]["pg_layer_name"]))
        self.assertLess(0, cur.rowcount, "Table of the layer_0 should have at least one row.")
        cur.execute("""SELECT id FROM {:s};""".format(self.params["layer_defs"]["layer_1"]["pg_layer_name"]))
        self.assertLess(0, cur.rowcount, "Table of the layer_1 should have at least one row.")

    def test_bad_file_aborts(self):
        from qc_tool.vector.import2pg import run_check
        bad_filepath = TEST_DATA_DIR.joinpath("raster", "checks", "r11", "test_raster1.tif")
        self.params.update({"layer_defs": {"layer_0": {"src_filepath": bad_filepath,
                                                       "src_layer_name": "irrelevant_layer",
                                                       "layer_alias": "layer_0"}},
                            "layers": ["layer_0"]})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status)

    def test_precision(self):
        """ogr2ogr parameter PRECISION=NO should supress numeric field overflow error."""
        from qc_tool.vector.import2pg import run_check
        shp_filepath = TEST_DATA_DIR.joinpath("vector", "checks", "import2pg", "field_overflow_example.shp")
        self.params.update({"layer_defs": {"layer_0": {"src_filepath": shp_filepath,
                                                       "src_layer_name": "field_overflow_example",
                                                       "layer_alias": "layer_0"}},
                            "layers": ["layer_0"]})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)


class Test_unique(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.params.update({"output_dir": self.params["jobdir_manager"].output_dir})

    def test(self):
        from qc_tool.vector.unique import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE mytable (fid integer, unique_1 varchar, unique_2 integer, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO mytable (fid, unique_1, unique_2, geom) VALUES "
                       " (1, 'a', 33, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                       " (2, 'b', 34, ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                       " (3, 'c', 35, ST_MakeEnvelope(3, 1, 4, 2, 4326));")
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "mytable",
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
                            "layers": ["layer_0"],
                            "unique_keys": ["unique_1", "unique_2"],
                            "step_nr": 1})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_fail(self):
        from qc_tool.vector.unique import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE mytable (fid integer, ident varchar, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO mytable (fid, ident, geom) VALUES "
                       " (1, 'a', ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                       " (2, 'b', ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                       " (3, 'b', ST_MakeEnvelope(3, 1, 4, 2, 4326));")
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "mytable",
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
                            "layers": ["layer_0"],
                            "unique_keys": ["ident"],
                            "step_nr": 1})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)
        self.assertEqual(1, len(status.messages))


class Test_enum(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.params.update({"output_dir": self.params["jobdir_manager"].output_dir})

    def test_string_codes(self):
        from qc_tool.vector.enum import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE xxx18_zz (fid integer, code_18 varchar, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO xxx18_zz VALUES (1, '112', ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                  " (2, '111', ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                                                  " (3, '111', ST_MakeEnvelope(3, 1, 4, 2, 4326));")
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "xxx18_zz",
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
                            "layers": ["layer_0"],
                            "column_defs": [["code_18", ["111", "112"]]],
                            "step_nr": 1})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_integer_codes(self):
        from qc_tool.vector.enum import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE xxx12_zz (fid integer, code_12 integer, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO xxx12_zz VALUES (1, 2, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                       " (2, 3, ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                       " (3, 4, ST_MakeEnvelope(3, 1, 4, 2, 4326));")
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "xxx12_zz",
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
                            "layers": ["layer_0"],
                            "column_defs": [["code_12", [1, 2, 3, 4]]],
                            "step_nr": 1})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_integer_codes_fail(self):
        from qc_tool.vector.enum import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE xxx12_zz (fid integer, code_12 integer, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO xxx12_zz VALUES (1, 2, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                       " (2, 9999, ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                       " (3, 9999, ST_MakeEnvelope(3, 1, 4, 2, 4326));")
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "xxx12_zz",
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
                            "layers": ["layer_0"],
                            "column_defs": [["code_12", [1, 2, 3, 4]]],
                            "step_nr": 1})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)

    def test_change_fail(self):
        from qc_tool.vector.enum import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE cha18_xx (fid integer, code_12 varchar, code_18 varchar, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO cha18_xx VALUES (1, '111', '112', ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                  " (2, 'xxx', 'xxx', ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                                                  " (3, 'xxx', '111', ST_MakeEnvelope(3, 1, 4, 2, 4326));")
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "cha18_xx",
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
                            "layers": ["layer_0"],
                            "column_defs": [["code_12", ["111", "112"]], ["code_18", ["111", "112"]]],
                            "step_nr": 1})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)
        self.assertEqual(2, len(status.messages))

    def test_null(self):
        """Enum check should fail if code column has NULL values."""
        from qc_tool.vector.enum import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE cha18_xx (fid integer, code_12 varchar, code_18 varchar, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO cha18_xx VALUES (1, '111', NULL, ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "cha18_xx",
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
                            "layers": ["layer_0"],
                            "column_defs": [["code_12", ["111", "112"]], ["code_18", ["111", "112"]]],
                            "step_nr": 1})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)
        self.assertEqual(1, len(status.messages))

    def test_exclude(self):
        from qc_tool.vector.enum import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE my_table (fid integer, code varchar, ua varchar, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO my_table VALUES (1, 'a', NULL, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                       " (2, 'b', NULL, ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                       " (3, 'x', 'ua2012', ST_MakeEnvelope(3, 1, 4, 2, 4326));")
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "my_table",
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
                            "layers": ["layer_0"],
                            "column_defs": [["code", ["a", "b"]]],
                            "exclude_column_name": "ua",
                            "step_nr": 1})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_exclude_fail(self):
        from qc_tool.vector.enum import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE my_table (fid integer, code varchar, ua varchar, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO my_table VALUES (1, 'a', NULL, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                       " (2, 'x', NULL, ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                       " (3, 'x', 'ua2006', ST_MakeEnvelope(3, 1, 4, 2, 4326));")
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "my_table",
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
                            "layers": ["layer_0"],
                            "column_defs": [["code", ["a", "b"]]],
                            "exclude_column_name": "ua",
                            "step_nr": 1})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)
        self.assertEqual(1, len(status.messages))


class Test_nodata(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.cursor = self.params["connection_manager"].get_connection().cursor()
        self.cursor.execute("CREATE TABLE mytable (fid integer, nodata integer, attr1 integer, attr2 integer);")
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "mytable",
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
                            "layers": ["layer_0"],
                            "nodata_column_name": "nodata",
                            "nodata_value": 1,
                            "dep_column_names": ["attr1", "attr2"],
                            "dep_value": 0,
                            "step_nr": 1})

    def test(self):
        from qc_tool.vector.nodata import run_check
        self.cursor.execute("INSERT INTO mytable VALUES ( 1, 0, 0, 0),"
                                                      " ( 2, 0, 0, 10),"
                                                      " ( 3, 0, 10, 0),"
                                                      " ( 4, 0, 10, 10),"
                                                      " ( 5, 0, NULL, 0),"
                                                      " ( 6, 0, NULL, 10),"
                                                      " ( 7, 0, 0, NULL),"
                                                      " ( 8, 0, 10, NULL),"
                                                      " ( 9, 0, NULL, NULL),"
                                                      " (10, 1, 0, 0);")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_fail(self):
        from qc_tool.vector.nodata import run_check
        self.cursor.execute("INSERT INTO mytable VALUES (1, 1, 0, 10);")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)

    def test_fail_null(self):
        from qc_tool.vector.nodata import run_check
        self.cursor.execute("INSERT INTO mytable VALUES (1, 1, 0, NULL);")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)

    def test_nodata_null(self):
        self.params["nodata_value"] = None
        from qc_tool.vector.nodata import run_check
        self.cursor.execute("INSERT INTO mytable VALUES ( 1, 0, 0, 0),"
                                                      " ( 2, 0, 0, 10),"
                                                      " ( 3, 0, 10, 0),"
                                                      " ( 4, 0, 10, 10),"
                                                      " ( 5, 0, NULL, 0),"
                                                      " ( 6, 0, NULL, 10),"
                                                      " ( 7, 0, 0, NULL),"
                                                      " ( 8, 0, 10, NULL),"
                                                      " ( 9, 0, NULL, NULL),"
                                                      " (10, NULL, 0, 0);")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_nodata_null_fail(self):
        self.params["nodata_value"] = None
        from qc_tool.vector.nodata import run_check
        self.cursor.execute("INSERT INTO mytable VALUES (1, NULL, 0, 10);")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)

    def test_nodata_null_fail_null(self):
        self.params["dep_value"] = None
        from qc_tool.vector.nodata import run_check
        self.cursor.execute("INSERT INTO mytable VALUES (1, 1, NULL, 10);")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)

    def test_dep_null(self):
        self.params["dep_value"] = None
        from qc_tool.vector.nodata import run_check
        self.cursor.execute("INSERT INTO mytable VALUES ( 1, 0, 0, 0),"
                                                      " ( 2, 0, 0, 10),"
                                                      " ( 3, 0, 10, 0),"
                                                      " ( 4, 0, 10, 10),"
                                                      " ( 5, 0, NULL, 0),"
                                                      " ( 6, 0, NULL, 10),"
                                                      " ( 7, 0, 0, NULL),"
                                                      " ( 8, 0, 10, NULL),"
                                                      " ( 9, 0, NULL, NULL),"
                                                      " (10, 1, NULL, NULL);")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)


class Test_non_probable(VectorCheckTestCase):
    def test(self):
        super().setUp()
        from qc_tool.vector.non_probable import run_check
        self.cursor = self.params["connection_manager"].get_connection().cursor()
        self.params.update({"layer_defs": {"change": {"pg_fid_name": "fid",
                                                      "pg_layer_name": "change_layer",
                                                      "fid_display_name": "row_number"}},
                            "layers": ["change"],
                            "initial_code_column_name": "code1",
                            "final_code_column_name": "code2",
                            "step_nr": 1})
        self.params.update({"changes": [["1", ["3", "4"]],
                                        ["2", ["4"]]]})
        self.cursor.execute("CREATE TABLE change_layer (fid integer, code1 char(1), code2 char(1));")
        self.cursor.execute("INSERT INTO change_layer VALUES (1, '1', '2'), (2, '1', '3'), (3, '1', '4'), (4, '2', '3'), (5, '2', '4');")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.cursor.execute("SELECT fid FROM s01_change_layer_warning ORDER BY fid;")
        self.assertListEqual([(2,), (3,), (5,)], self.cursor.fetchall())


class Test_singlepart(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.params.update({"output_dir": self.params["jobdir_manager"].output_dir})

    def test(self):
        from qc_tool.vector.singlepart import run_check
        status = self.status_class()
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE mytable (fid integer, geom geometry(Multipolygon, 4326));")
        cursor.execute("INSERT INTO mytable "
                       "VALUES (1, ST_Multi(ST_MakeEnvelope(0, 0, 1, 1, 4326))),"
                       "       (3, ST_Multi(ST_MakeEnvelope(3, 3, 4, 4, 4326)));")
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "mytable",
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
                            "layers": ["layer_0"],
                            "step_nr": 1})
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_fail(self):
        from qc_tool.vector.singlepart import run_check
        status = self.status_class()
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE mytable (fid integer, geom geometry(Multipolygon, 4326));")
        cursor.execute("INSERT INTO mytable "
                       "VALUES (1, ST_Union(ST_MakeEnvelope(0, 0, 1, 1, 4326), "
                       "                    ST_MakeEnvelope(3, 3, 4, 4, 4326)));")
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "mytable",
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
                            "layers": ["layer_0"],
                            "step_nr": 1})
        run_check(self.params, status)
        self.assertEqual("aborted", status.status)


class Test_geometry(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.cursor = self.params["connection_manager"].get_connection().cursor()
        self.cursor.execute("CREATE TABLE test_layer (fid integer, geom geometry(Polygon, 4326));")
        self.cursor.execute("INSERT INTO test_layer VALUES (1, ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        self.params.update({"layer_defs": {"test": {"pg_fid_name": "fid",
                                                    "pg_layer_name": "test_layer",
                                                    "fid_display_name": "row number"}},
                            "layers": ["test"],
                            "step_nr": 1})

    def test(self):
        from qc_tool.vector.geometry import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_intersecting_ring_forming_hole_fails(self):
        """ESRI shapefile allows this, OGC simple features does not. Requirement is to follow OGC specification."""
        from qc_tool.vector.geometry import run_check
        self.cursor.execute("INSERT INTO test_layer VALUES (2, ST_PolygonFromText("
                            "'POLYGON((0 0, 2 0, 1 1, 3 1, 2 0, 4 0, 4 4, 0 4, 0 0))', 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status)

    def test_self_intersecting_ring_fails(self):
        from qc_tool.vector.geometry import run_check
        self.cursor.execute("INSERT INTO test_layer VALUES (2, ST_PolygonFromText('POLYGON((0 0, 1 0, 0 1, 1 1, 0 0))', 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status)


class Test_area(VectorCheckTestCase):
    def test(self):
        from qc_tool.vector.area import run_check
        self.cursor = self.params["connection_manager"].get_connection().cursor()
        self.cursor.execute("CREATE TABLE test (fid integer, area_ha real, geom geometry(Polygon, 4326));")
        self.cursor.execute("INSERT INTO test VALUES (1, 1.0, ST_MakeEnvelope(0, 0, 10000, 0.5, 4326)),"
                                                   " (2, 1.0, ST_MakeEnvelope(0, 0, 10000, 0.9998, 4326)),"
                                                   " (3, 1.0, ST_MakeEnvelope(0, 0, 10000, 0.9999, 4326)),"
                                                   " (4, 1.0, ST_MakeEnvelope(0, 0, 10000, 1, 4326)),"
                                                   " (5, 1.0, ST_MakeEnvelope(0, 0, 10000, 1.0001, 4326)),"
                                                   " (6, 1.0, ST_MakeEnvelope(0, 0, 10000, 1.0002, 4326)),"
                                                   " (7, 1.0, ST_MakeEnvelope(0, 0, 10000, 2, 4326));")
        self.params.update({"layer_defs": {"test": {"pg_layer_name": "test",
                                                    "pg_fid_name": "fid",
                                                    "fid_display_name": "row number"}},
                            "layers": ["test"],
                            "area_column_name": "area_ha",
                            "unit": 10000,
                            "tolerance": 0.0001,
                            "step_nr": 1})
        status = self.status_class()
        run_check(self.params, status)
        self.cursor.execute("SELECT fid FROM s01_test_error ORDER BY fid;")
        self.assertListEqual([(1,), (2,), (6,), (7,)], self.cursor.fetchall())


class Test_compactness(VectorCheckTestCase):
    def test(self):
        from qc_tool.vector.compactness import run_check
        self.cursor = self.params["connection_manager"].get_connection().cursor()
        self.cursor.execute("CREATE TABLE test (fid integer, code char(1), area real, geom geometry(Polygon, 4326));")
        self.cursor.execute("INSERT INTO test VALUES (1, '1', 1, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                   " (2, '1', 1.1, ST_MakeEnvelope(0, 0, 1, 1.1, 4326)),"
                                                   " (3, '2', 1, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                   " (4, '2', 1.1, ST_MakeEnvelope(0, 0, 1, 1.1, 4326)),"
                                                   " (5, NULL, 1, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                   " (6, NULL, 1.1, ST_MakeEnvelope(0, 0, 1, 1.1, 4326));")
        self.params.update({"layer_defs": {"test": {"pg_layer_name": "test",
                                                    "pg_fid_name": "fid",
                                                    "fid_display_name": "row number"}},
                            "layers": ["test"],
                            "area_column_name": "area",
                            "code_column_name": "code",
                            "linear_code": '1',
                            "patchy_code": '2',
                            "threshold": 0.785,
                            "step_nr": 1})
        status = self.status_class()
        run_check(self.params, status)
        self.cursor.execute("SELECT fid FROM s01_test_linear_error ORDER BY fid;")
        self.assertListEqual([(1,)], self.cursor.fetchall())
        self.cursor.execute("SELECT fid FROM s01_test_patchy_error ORDER BY fid;")
        self.assertListEqual([(4,)], self.cursor.fetchall())


class Test_gap(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.cursor = self.params["connection_manager"].get_connection().cursor()
        self.cursor.execute("CREATE TABLE boundary (geom geometry(Polygon, 4326));")
        self.cursor.execute("INSERT INTO boundary VALUES (ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        self.cursor.execute("INSERT INTO boundary VALUES (ST_Difference(ST_MakeEnvelope(2, 2, 5, 5, 4326),"
                                                                      " ST_MakeEnvelope(3, 3, 4, 4, 4326)));")
        self.cursor.execute("CREATE TABLE reference (xfid integer, geom geometry(Polygon, 4326));")
        self.params.update({"layer_defs": {"reference": {"pg_layer_name": "reference",
                                                         "pg_fid_name": "xfid"},
                                           "boundary": {"pg_layer_name": "boundary"}},
                            "layers": ["reference"],
                            "du_column_name": None,
                            "step_nr": 1})

    def test_tolerance(self):
        from qc_tool.vector.gap import run_check
        self.cursor.execute("INSERT INTO reference VALUES (1, ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        self.cursor.execute("INSERT INTO reference VALUES (2, ST_MakeEnvelope(2.009, 2.009, 5, 5, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.cursor.execute("SELECT ST_AsText(geom) FROM s01_reference_gap_error;")
        self.assertEqual([], self.cursor.fetchall())

    def test_tolerance_finds_gaps(self):
        from qc_tool.vector.gap import run_check
        self.cursor.execute("INSERT INTO reference VALUES (1, ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        self.cursor.execute("INSERT INTO reference VALUES (2, ST_MakeEnvelope(2.05, 2.05, 5, 5, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.cursor.execute("SELECT ST_AsText(geom) FROM s01_reference_gap_error;")
        self.assertEqual(1, len(self.cursor.fetchall()))
        self.assertIn("has 1 gaps", status.messages[0])


    def test(self):
        from qc_tool.vector.gap import run_check
        self.cursor.execute("INSERT INTO reference VALUES (1, ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        self.cursor.execute("INSERT INTO reference VALUES (2, ST_MakeEnvelope(2, 2, 4, 5, 4326));")
        self.cursor.execute("INSERT INTO reference VALUES (3, ST_MakeEnvelope(4, 2, 5, 5, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.cursor.execute("SELECT ST_AsText(geom) FROM s01_reference_gap_error;")
        self.assertEqual([], self.cursor.fetchall())

    def test_gap_error(self):
        from qc_tool.vector.gap import run_check
        self.cursor.execute("INSERT INTO reference VALUES (1, ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.assertIn("gap", status.messages[0])
        self.cursor.execute("SELECT ST_AsText(geom) FROM s01_reference_gap_error;")
        self.assertEqual([('POLYGON((2 2,2 5,5 5,5 2,2 2),(3 3,4 3,4 4,3 4,3 3))',)], self.cursor.fetchall())


class Test_gap_du(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.cursor = self.params["connection_manager"].get_connection().cursor()
        self.cursor.execute("CREATE TABLE boundary (unit CHAR(1), geom geometry(Polygon, 4326));")
        self.cursor.execute("INSERT INTO boundary VALUES ('A', ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        self.cursor.execute("INSERT INTO boundary VALUES ('A', ST_Difference(ST_MakeEnvelope(2, 2, 5, 5, 4326),"
                                                                           " ST_MakeEnvelope(3, 3, 4, 4, 4326)));")
        self.cursor.execute("INSERT INTO boundary VALUES ('B', ST_MakeEnvelope(6, 6, 7, 7, 4326));")
        self.cursor.execute("INSERT INTO boundary VALUES ('B', ST_MakeEnvelope(8, 8, 9, 9, 4326));")
        self.cursor.execute("INSERT INTO boundary VALUES ('C', ST_MakeEnvelope(10, 10, 11, 11, 4326));")
        self.cursor.execute("CREATE TABLE reference (xfid integer, unit CHAR(1), geom geometry(Polygon, 4326));")
        self.params.update({"layer_defs": {"reference": {"pg_layer_name": "reference",
                                                         "pg_fid_name": "xfid"},
                                           "boundary": {"pg_layer_name": "boundary"}},
                            "layers": ["reference"],
                            "du_column_name": "unit",
                            "step_nr": 1})

    def test(self):
        from qc_tool.vector.gap import run_check
        self.cursor.execute("INSERT INTO reference VALUES (1, 'A', ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        self.cursor.execute("INSERT INTO reference VALUES (2, 'A', ST_MakeEnvelope(2, 2, 4, 5, 4326));")
        self.cursor.execute("INSERT INTO reference VALUES (3, 'A', ST_MakeEnvelope(4, 2, 5, 5, 4326));")
        self.cursor.execute("INSERT INTO reference VALUES (4, 'B', ST_MakeEnvelope(6, 6, 9, 9, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.cursor.execute("SELECT ST_AsText(geom) FROM s01_reference_gap_error;")
        self.assertListEqual([], self.cursor.fetchall())

    def test_gap_error(self):
        from qc_tool.vector.gap import run_check
        self.cursor.execute("INSERT INTO reference VALUES (1, 'A', ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        self.cursor.execute("INSERT INTO reference VALUES (2, 'A', ST_MakeEnvelope(2, 2, 5, 5, 4326));")
        self.cursor.execute("INSERT INTO reference VALUES (3, 'B', ST_MakeEnvelope(6, 6, 7, 7, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.assertIn("gap", status.messages[0])
        self.cursor.execute("SELECT ST_AsText(geom) FROM s01_reference_gap_error;")
        self.assertListEqual([('POLYGON((8 8,8 9,9 9,9 8,8 8))',)], self.cursor.fetchall())

    def test_du_warning(self):
        from qc_tool.vector.gap import run_check
        self.cursor.execute("INSERT INTO reference VALUES (1, 'A', ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        self.cursor.execute("INSERT INTO reference VALUES (2, 'D', ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        self.cursor.execute("INSERT INTO reference VALUES (3, NULL, ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.cursor.execute("SELECT * FROM s01_reference_du_warning;")
        self.assertListEqual([(2,), (3,)], self.cursor.fetchall())


class Test_mxmu(VectorCheckTestCase):
    def test(self):
        from qc_tool.vector.mxmu import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE reference (fid integer, code varchar, shape_area real, geom geometry(Polygon, 4326));")

        # General features, class 1.
        cursor.execute("INSERT INTO reference VALUES (10, 'code1', 500000, ST_MakeEnvelope(10, 1, 11, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (12, 'code1', 600000, ST_MakeEnvelope(12, 0, 13, 2, 4326));")

        # General features, class 2.
        cursor.execute("INSERT INTO reference VALUES (14, 'code2', 499999, ST_MakeEnvelope(14, 1, 15, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (16, 'code2', 500000, ST_MakeEnvelope(16, 0, 17, 2, 4326));")

        # Excluded feature.
        cursor.execute("INSERT INTO reference VALUES (30, 'code1', 500001, ST_MakeEnvelope(10.1, 1.1, 10.9, 1.9, 4326));")

        # Error feature.
        cursor.execute("INSERT INTO reference VALUES (31, 'code2', 500001, ST_MakeEnvelope(14.1, 1.1, 14.9, 1.9, 4326));")

        self.params.update({"layer_defs": {"reference": {"pg_layer_name": "reference",
                                                         "pg_fid_name": "fid",
                                                         "fid_display_name": "row number"}},
                            "layers": ["reference"],
                            "mxmu": 500000,
                            "area_column_name": "shape_area",
                            "error_where": "layer.code = 'code2'",
                            "step_nr": 1})
        run_check(self.params, self.status_class())
        cursor.execute("SELECT fid FROM s01_reference_error ORDER BY fid;")
        self.assertListEqual([(31,)], cursor.fetchall())

class Test_mmw(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.params.update({"layer_defs": {"mmw": {"pg_layer_name": "mmw",
                                                   "pg_fid_name": "fid",
                                                   "fid_display_name": "row number"}},
                            "layers": ["mmw"],
                            "mmw": 1.0,
                            "general_where": "FALSE",
                            "exception_where": "FALSE",
                            "step_nr": 1})

    def test(self):
        from qc_tool.vector.mmw import run_check

        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE mmw (fid integer, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO mmw VALUES (1, ST_MakeEnvelope(0, 0, 3, 0.999, 4326));")
        cursor.execute("INSERT INTO mmw VALUES (2, ST_MakeEnvelope(0, 0, 3, 1, 4326));")
        cursor.execute("INSERT INTO mmw VALUES (3, ST_MakeEnvelope(0, 0, 3, 1.001, 4326));")
        cursor.execute("INSERT INTO mmw VALUES (4, ST_Difference(ST_MakeEnvelope(40, 0, 49, 9, 4326),"
                                                               " ST_MakeEnvelope(43, 0, 46, 8, 4326)));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        cursor.execute("SELECT fid FROM s01_mmw_warning ORDER BY fid;")
        self.assertListEqual([(1,), (2,), (4,)], cursor.fetchall())

    def test_patchy(self):
        from qc_tool.vector.mmw import run_check

        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE mmw (fid integer, code char(1), geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO mmw VALUES (1, NULL, ST_MakeEnvelope(0, 0, 3, 0.999, 4326));")
        cursor.execute("INSERT INTO mmw VALUES (2, '1', ST_MakeEnvelope(0, 0, 3, 0.999, 4326));")
        cursor.execute("INSERT INTO mmw VALUES (3, '2', ST_MakeEnvelope(0, 0, 3, 0.999, 4326));")
        cursor.execute("INSERT INTO mmw VALUES (4, '2', ST_MakeEnvelope(0, 0, 3, 1.001, 4326));")

        self.params["general_where"] = "layer.code IS NULL OR layer.code = '1'"
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        cursor.execute("SELECT fid FROM s01_mmw_warning ORDER BY fid;")
        self.assertListEqual([(3,)], cursor.fetchall())

    def test_exception(self):
        from qc_tool.vector.mmw import run_check

        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE mmw (fid integer, code char(5), geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO mmw VALUES (1, '12', ST_MakeEnvelope(10, 0, 13, 0.999, 4326));")
        cursor.execute("INSERT INTO mmw VALUES (2, '12', ST_MakeEnvelope(20, 0, 23, 1, 4326));")
        cursor.execute("INSERT INTO mmw VALUES (3, '12', ST_MakeEnvelope(30, 0, 33, 1.001, 4326));")
        cursor.execute("INSERT INTO mmw VALUES (4, '12', ST_Difference(ST_MakeEnvelope(40, 0, 49, 9, 4326),"
                                                                     " ST_MakeEnvelope(43, 0, 46, 8, 4326)));")
        cursor.execute("INSERT INTO mmw VALUES (5, '122', ST_MakeEnvelope(50, 0, 53, 1, 4326));")

        self.params["exception_where"] = "layer.code LIKE '122%'"
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        cursor.execute("SELECT fid FROM s01_mmw_exception ORDER BY fid;")
        self.assertListEqual([(5,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM s01_mmw_warning ORDER BY fid;")
        self.assertListEqual([(1,), (2,), (4,)], cursor.fetchall())


class Test_mxmw(VectorCheckTestCase):
    def test(self):
        from qc_tool.vector.mxmw import run_check
        self.params.update({"layer_defs": {"mxmw": {"pg_layer_name": "mxmw",
                                                   "pg_fid_name": "fid",
                                                   "fid_display_name": "row number"}},
                            "layers": ["mxmw"],
                            "mxmw": 1.0,
                            "warning_where": "layer.code = '1'",
                            "step_nr": 1})
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE mxmw (fid integer, code char(1), geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO mxmw VALUES (1, NULL, ST_MakeEnvelope(0, 0, 3, 2, 4326));")
        cursor.execute("INSERT INTO mxmw VALUES (2, '1', ST_MakeEnvelope(0, 0, 3, 0.999, 4326));")
        cursor.execute("INSERT INTO mxmw VALUES (3, '1', ST_MakeEnvelope(0, 0, 3, 1.001, 4326));")
        cursor.execute("INSERT INTO mxmw VALUES (4, '2', ST_MakeEnvelope(0, 0, 3, 2, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        cursor.execute("SELECT fid FROM s01_mxmw_warning ORDER BY fid;")
        self.assertListEqual([(3,)], cursor.fetchall())


class Test_mml(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.params.update({"layer_defs": {"mml": {"pg_layer_name": "mml",
                                                   "pg_fid_name": "fid",
                                                   "fid_display_name": "row number"}},
                            "layers": ["mml"],
                            "mml": 10.,
                            "warning_where": "code = '1'",
                            "step_nr": 1})
        self.cursor = self.params["connection_manager"].get_connection().cursor()
        self.cursor.execute("CREATE TABLE mml (fid integer, code char(1), geom geometry(Polygon, 4326));")

    def test(self):
        from qc_tool.vector.mml import run_check
        self.cursor.execute("INSERT INTO mml VALUES (1, NULL, ST_MakeEnvelope(0, 0, 5, 1, 4326));")
        self.cursor.execute("INSERT INTO mml VALUES (2, '1', ST_MakeEnvelope(0, 0, 5, 1, 4326));")
        self.cursor.execute("INSERT INTO mml VALUES (3, '1', ST_MakeEnvelope(0, 0, 9.999, 1, 4326));")
        self.cursor.execute("INSERT INTO mml VALUES (4, '1', ST_MakeEnvelope(0, 0, 10, 1, 4326));")
        self.cursor.execute("INSERT INTO mml VALUES (5, '1', ST_MakeEnvelope(0, 0, 11, 1, 4326));")
        self.cursor.execute("INSERT INTO mml VALUES (6, '2', ST_MakeEnvelope(0, 0, 5, 1, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.cursor.execute("SELECT fid FROM s01_mml_warning ORDER BY fid;")
        self.assertListEqual([(2,), (3,)], self.cursor.fetchall())

    def test_arch(self):
        """The plain box does not pass the check, however, if we make an arch from it, the check passes."""
        from qc_tool.vector.mml import run_check
        self.cursor.execute("INSERT INTO mml VALUES (1, '1', ST_Difference(ST_MakeEnvelope(0, 0, 9.999, 1, 4326),"
                                                                         " ST_MakeEnvelope(0.5, 0, 9.5, 0.5, 4326)));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.cursor.execute("SELECT fid FROM s01_mml_warning ORDER BY fid;")
        self.assertListEqual([], self.cursor.fetchall())

    def test_inner_ring(self):
        """If there are two inner rings intersecting in a point, then ST_ApproximateMedialAxis() raises error:

          psycopg2.InternalError: straight skeleton of Polygon with touching interior rings is not implemented

        Adapted implementation ignores inner rings, so this test should pass with ok status."""
        from qc_tool.vector.mml import run_check
        self.cursor.execute("INSERT INTO mml VALUES (1, '1', ST_Difference(ST_Difference(ST_MakeEnvelope(0, 0, 4, 4, 4326),"
                                                                                       " ST_MakeEnvelope(1, 0, 2, 2, 4326)),"
                                                                         " ST_MakeEnvelope(2, 2, 3, 3, 4326)));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.cursor.execute("SELECT fid FROM s01_mml_warning ORDER BY fid;")
        self.assertListEqual([(1,)], self.cursor.fetchall())


class Test_overlap(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.cursor = self.params["connection_manager"].get_connection().cursor()
        self.cursor.execute("CREATE TABLE layer_1 (fid integer, geom geometry(Polygon, 4326));")
        self.cursor.execute("CREATE TABLE layer_2 (fid integer, geom geometry(Polygon, 4326));")
        self.params.update({"layer_defs": {"layer_1": {"pg_layer_name": "layer_1",
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number",
                                                       "layer_alias": "layer_1"},
                                           "layer_2": {"pg_layer_name": "layer_2",
                                                       "layer_alias": "layer_2",
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
                            "layers": ["layer_1", "layer_2"],
                            "step_nr": 1})

    def test_non_overlapping(self):
        from qc_tool.vector.overlap import run_check
        self.cursor.execute("INSERT INTO layer_1 VALUES (1, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                           " (2, ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                                                           " (3, ST_MakeEnvelope(3, 1, 4, 2, 4326)),"
                                                           " (4, ST_MakeEnvelope(4, 1, 5, 2, 4326));")
        self.cursor.execute("INSERT INTO layer_2 VALUES (1, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                           " (2, ST_MakeEnvelope(2, 0, 3, 1, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_overlapping_fails(self):
        from qc_tool.vector.overlap import run_check
        self.cursor.execute("INSERT INTO layer_1 VALUES (1, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                           " (5, ST_MakeEnvelope(0.9, 0, 2, 1, 4326));")
        self.cursor.execute("INSERT INTO layer_2 VALUES (1, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                           " (5, ST_MakeEnvelope(0.9, 0, 2, 1, 4326)),"
                                                           " (6, ST_MakeEnvelope(0.8, 0, 3, 1, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)
        self.cursor.execute("SELECT fid FROM s01_layer_1_error ORDER BY fid;")
        self.assertListEqual([(1,), (5,)], self.cursor.fetchall())
        self.cursor.execute("SELECT fid FROM s01_layer_2_error ORDER BY fid;")
        self.assertListEqual([(1,), (5,), (6,)], self.cursor.fetchall())


class Test_neighbour(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.cursor = self.params["connection_manager"].get_connection().cursor()
        self.cursor.execute("CREATE TABLE test_layer (fid integer, code1 char(1), code2 char(1), geom geometry(Polygon, 4326));")
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "test_layer",
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
                            "layers": ["layer_0"],
                            "code_column_names": ["code1", "code2"],
                            "exception_where": ["FALSE"],
                            "error_where": ["TRUE"],
                            "step_nr": 1})

    def test_disjoint(self):
        from qc_tool.vector.neighbour import run_check
        self.cursor.execute("INSERT INTO test_layer VALUES (1, 'A', 'A', ST_MakeEnvelope(1, 0, 2, 1, 4326)),"
                                                         " (2, 'A', 'A', ST_MakeEnvelope(3, 0, 4, 1, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_different_class(self):
        from qc_tool.vector.neighbour import run_check
        self.cursor.execute("INSERT INTO test_layer VALUES (1, 'A', 'A', ST_MakeEnvelope(1, 0, 2, 1, 4326)),"
                                                         " (2, 'B', 'B', ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                                                         " (3, 'C', 'B', ST_MakeEnvelope(3, 0, 4, 1, 4326)),"
                                                         " (4, 'C', 'C', ST_MakeEnvelope(4, 0, 5, 1, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_touching_point(self):
        from qc_tool.vector.neighbour import run_check
        self.cursor.execute("INSERT INTO test_layer VALUES (1, 'A', 'A', ST_MakeEnvelope(1, 0, 2, 1, 4326)),"
                                                         " (2, 'A', 'A', ST_MakeEnvelope(2, 1, 3, 2, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_touching_line_fails(self):
        from qc_tool.vector.neighbour import run_check
        self.cursor.execute("INSERT INTO test_layer VALUES (1, 'A', 'A', ST_MakeEnvelope(1, 0, 2, 1, 4326)),"
                                                         " (2, 'A', 'A', ST_MakeEnvelope(2, 0, 3, 1, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)

    def test_complex_geom_fails(self):
        from qc_tool.vector.neighbour import run_check
        polygon = "POLYGON((2 0, 2 0.5, 2.5 0.5, 2 1, 2 1.5, 2.5 1.5, 2 2, 2.5 2, 2 2.5, 2.5 2.5, 3 3, 3 0, 2 0))"
        create_sql = ("INSERT INTO test_layer VALUES (1, 'A', 'A', ST_MakeEnvelope(1, 0, 2, 3, 4326)),"
                                                   " (2, 'A', 'A', ST_PolygonFromText('" + polygon + "', 4326));")
        self.cursor.execute(create_sql)
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)

    def test_exclude(self):
        from qc_tool.vector.neighbour import run_check
        self.cursor.execute("INSERT INTO test_layer VALUES (1, 'A', 'B', ST_MakeEnvelope(1, 0, 2, 1, 4326)),"
                                                         " (2, 'A', 'B', ST_MakeEnvelope(2, 0, 3, 1, 4326));")
        self.params["error_where"] = ["layer.code2 <> 'B' AND other.code2 <> 'B'"]
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_exclude_fails(self):
        from qc_tool.vector.neighbour import run_check
        self.cursor.execute("INSERT INTO test_layer VALUES (1, 'A', 'B', ST_MakeEnvelope(1, 0, 2, 1, 4326)),"
                                                         " (2, 'A', 'B', ST_MakeEnvelope(2, 0, 3, 1, 4326));")
        self.params["error_where"] = ["layer.code2 <> 'C' AND other.code2 <> 'C'"]
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)


class Test_neighbour_technical(VectorCheckTestCase):
    """Test neighbouring polygons taking into account technical change."""
    def setUp(self):
        super().setUp()
        self.cursor = self.params["connection_manager"].get_connection().cursor()
        self.cursor.execute("CREATE TABLE layer_0 (fid integer, code1 char(1), code2 char(1), chtype char(1), geom geometry(Polygon, 4326));")
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "layer_0",
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
                            "layers": ["layer_0"],
                            "code_column_names": ["code1", "code2"],
                            "exception_where": ["layer.chtype = 'T'"],
                            "error_where": ["TRUE"],
                            "step_nr": 1})

    def test_non_neighbouring(self):
        from qc_tool.vector.neighbour import run_check
        self.cursor.execute("INSERT INTO layer_0 VALUES (1, 'A', 'A', 'R', ST_MakeEnvelope(1, 0, 1.5, 1, 4326)),"
                                                      " (2, 'A', 'A', 'R', ST_MakeEnvelope(2, 0, 2.5, 1, 4326)),"
                                                      " (3, 'A', 'A', 'R', ST_MakeEnvelope(3, 0, 3.5, 1, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_exception(self):
        from qc_tool.vector.neighbour import run_check
        self.cursor.execute("INSERT INTO layer_0 VALUES (1, 'A', 'A', 'R', ST_MakeEnvelope(1, 0, 2, 1, 4326)),"
                                                       " (2, 'A', 'A', 'T', ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                                                       " (3, 'A', 'A', 'T', ST_MakeEnvelope(3, 0, 4, 1, 4326)),"
                                                       " (4, 'A', 'A', NULL, ST_MakeEnvelope(4, 0, 5, 1, 4326)),"
                                                       " (5, 'A', 'B', NULL, ST_MakeEnvelope(5, 0, 6, 1, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)
        self.cursor.execute("SELECT * FROM s01_layer_0_exception ORDER BY fid;")
        self.assertListEqual([(1,), (2,), (3,), (4,)], self.cursor.fetchall())
        self.cursor.execute("SELECT * FROM s01_layer_0_error ORDER BY fid;")
        self.assertListEqual([(1,), (2,), (3,), (4,)], self.cursor.fetchall())

    def test_error(self):
        from qc_tool.vector.neighbour import run_check
        self.cursor.execute("INSERT INTO layer_0 VALUES (1, 'A', 'A', 'R', ST_MakeEnvelope(1, 0, 2, 1, 4326)),"
                                                      " (2, 'A', 'A', 'R', ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                                                      " (3, 'A', 'A', 'T', ST_MakeEnvelope(3, 0, 4, 1, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)
        self.cursor.execute("SELECT * FROM s01_layer_0_exception ORDER BY fid;")
        self.assertListEqual([(2,), (3,)], self.cursor.fetchall())
        self.cursor.execute("SELECT * FROM s01_layer_0_error ORDER BY fid;")
        self.assertListEqual([(1,), (2,), (3,)], self.cursor.fetchall())


class Test_neighbour_comment(VectorCheckTestCase):
    def test(self):
        from qc_tool.vector.neighbour import run_check
        self.cursor = self.params["connection_manager"].get_connection().cursor()
        self.cursor.execute("CREATE TABLE rpz_layer (fid integer, code char(1), comment varchar, geom geometry(Polygon, 4326));")
        self.cursor.execute("INSERT INTO rpz_layer VALUES (1, 'A', 'Comment 1', ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        self.cursor.execute("INSERT INTO rpz_layer VALUES (2, 'A', 'Comment 2', ST_MakeEnvelope(1, 0, 2, 1, 4326));")
        self.cursor.execute("INSERT INTO rpz_layer VALUES (3, 'A',        NULL, ST_MakeEnvelope(2, 0, 3, 1, 4326));")
        self.cursor.execute("INSERT INTO rpz_layer VALUES (4, 'B',        'hu', ST_MakeEnvelope(3, 0, 4, 1, 4326));")
        self.cursor.execute("INSERT INTO rpz_layer VALUES (5, 'B', 'Comment 1', ST_MakeEnvelope(4, 0, 5, 1, 4326));")

        self.params.update({"layer_defs": {"rpz": {"pg_layer_name": "rpz_layer",
                                                   "pg_fid_name": "fid",
                                                   "fid_display_name": "row number"}},
                            "layers": ["rpz"],
                            "code_column_names": ["code"],
                            "exception_where": ["(layer.comment IS NOT NULL",
                                                " AND has_comment(layer.comment, ARRAY['Comment 1']))",
                                                "OR",
                                                "(other.comment IS NOT NULL",
                                                " AND has_comment(other.comment, ARRAY['Comment 1']))"],
                            "error_where": ["TRUE"],
                            "step_nr": 1})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)
        self.cursor.execute("SELECT fid FROM s01_rpz_layer_exception ORDER BY fid;")
        self.assertListEqual([(1,), (2,), (4,), (5,)], self.cursor.fetchall())
        self.cursor.execute("SELECT fid FROM s01_rpz_layer_error ORDER BY fid;")
        self.assertListEqual([(2,), (3,)], self.cursor.fetchall())


class Test_change(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "mytable",
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
                            "layers": ["layer_0"],
                            "initial_code_column_name": "code_1",
                            "final_code_column_name": "code_2",
                            "step_nr": 1})

    def test(self):
        from qc_tool.vector.change import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE mytable (fid integer, code_1 varchar, code_2 varchar, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO mytable VALUES (1, 'a', 'b', ST_MakeEnvelope(1, 0, 2, 1, 4326)),"
                                                 " (2, 'a', 'c', ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                                                 " (3, 'a', 'c', ST_MakeEnvelope(3, 0, 4, 1, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.assertEqual(0, len(status.messages))
        cursor.execute("SELECT * FROM s01_mytable_exception ORDER BY fid;")
        self.assertListEqual([], cursor.fetchall())
        cursor.execute("SELECT * FROM s01_mytable_error ORDER BY fid;")
        self.assertListEqual([], cursor.fetchall())

    def test_fail(self):
        from qc_tool.vector.change import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE mytable (fid integer, code_1 varchar, code_2 varchar, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO mytable VALUES (1, 'a', 'b', ST_MakeEnvelope(1, 0, 2, 1, 4326)),"
                                                 " (2, 'a', 'a', ST_MakeEnvelope(2, 0, 3, 1, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)
        self.assertEqual(1, len(status.messages))
        cursor.execute("SELECT * FROM s01_mytable_exception ORDER BY fid;")
        self.assertListEqual([], cursor.fetchall())
        cursor.execute("SELECT * FROM s01_mytable_error ORDER BY fid;")
        self.assertListEqual([(2,)], cursor.fetchall())


class Test_change_technical(VectorCheckTestCase):
    """Test change polygons taking into account technical change."""
    def setUp(self):
        super().setUp()
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "mytable",
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
                            "layers": ["layer_0"],
                            "initial_code_column_name": "code_1",
                            "final_code_column_name": "code_2",
                            "chtype_column_name": "chtype",
                            "step_nr": 1})

    def test_technical(self):
        from qc_tool.vector.change import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE mytable (fid integer, code_1 varchar, code_2 varchar, chtype varchar, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO mytable VALUES (1, 'a', 'b', NULL, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                 " (2, 'a', 'c', 'R', ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                                                 " (3, 'a', 'a', 'T', ST_MakeEnvelope(3, 1, 4, 2, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.assertEqual(1, len(status.messages))
        cursor.execute("SELECT * FROM s01_mytable_exception ORDER BY fid;")
        self.assertListEqual([(3,)], cursor.fetchall())

    def test_chtype_fail(self):
        from qc_tool.vector.change import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE mytable (fid integer, code_1 varchar, code_2 varchar, chtype varchar, geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO mytable VALUES (1, 'a', 'b', 'R', ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                 " (2, 'a', 'a', 'R', ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                                                 " (3, 'a', 'a', 'T', ST_MakeEnvelope(3, 1, 4, 2, 4326)),"
                                                 " (4, 'a', 'a', NULL, ST_MakeEnvelope(4, 2, 5, 3, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)
        self.assertEqual(2, len(status.messages))
        cursor.execute("SELECT * FROM s01_mytable_exception ORDER BY fid;")
        self.assertListEqual([(3,)], cursor.fetchall())
        cursor.execute("SELECT * FROM s01_mytable_error ORDER BY fid;")
        self.assertListEqual([(2,), (4,)], cursor.fetchall())


class Test_layer_area(VectorCheckTestCase):
    def setUp(self):
        super().setUp()

        self.params["tmp_dir"] = self.params["jobdir_manager"].tmp_dir
        self.params["output_dir"] = self.params["jobdir_manager"].output_dir
        self.params["error_percent_difference"] = 0.1
        self.params["warning_percent_difference"] = 0.05

        # Create an example raster layer with sum area = 250 m2
        raster_src_filepath = self.params["tmp_dir"].joinpath("test_raster.tif")
        self.params["raster_layer_defs"] = {"raster_1": {"src_filepath": str(raster_src_filepath),
                                             "src_layer_name": "raster_1"}}
        array = np.array([[3, 3, 3, 3],
                          [1, 1, 1, 1],
                          [1, 1, 0, 0],
                          [0, 0, 0, 0]])
        cols = array.shape[1]
        rows = array.shape[0]
        originX = 0
        originY = 0
        pixelWidth = 5
        pixelHeight = 5

        driver = gdal.GetDriverByName('GTiff')
        outRaster = driver.Create(str(raster_src_filepath), cols, rows, 1, gdal.GDT_Byte)
        outRaster.SetGeoTransform((originX, pixelWidth, 0, originY, 0, pixelHeight))
        outband = outRaster.GetRasterBand(1)
        outband.WriteArray(array)
        outRasterSRS = osr.SpatialReference()
        outRasterSRS.ImportFromEPSG(3035)
        outRaster.SetProjection(outRasterSRS.ExportToWkt())
        outband.FlushCache()

        # Create an example vector layer.
        self.cursor = self.params["connection_manager"].get_connection().cursor()
        self.params.update({"layer_defs": {"vector_1": {"pg_layer_name": "vector_1",
                                                        "pg_fid_name": "fid",
                                                        "fid_display_name": "row number"}},
                            "vector_layer": "vector_1",
                            "raster_layer_defs": {"raster_1": {"src_filepath": str(raster_src_filepath),
                                                               "src_layer_name": "raster_1"}},
                            "raster_layer": "raster_1",
                            "vector_code_column_name": "code",
                            "vector_codes": ["A", "B"],
                            "raster_codes": [1, 3],
                            "step_nr": 1})
        self.cursor.execute("CREATE TABLE vector_1 (fid integer, code varchar, geom geometry(Polygon, 3035));")

    def test(self):
        from qc_tool.vector.layer_area import run_check
        # 20 x 10 m polygon (area 200 m2)
        self.cursor.execute("INSERT INTO vector_1 VALUES (1, 'A', ST_MakeEnvelope(0, 10, 20, 20, 3035));")

        # 10 x 5 m polygon (area 50 m2)
        self.cursor.execute("INSERT INTO vector_1 VALUES (1, 'B', ST_MakeEnvelope(0, 5, 10, 10, 3035));")

        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_fail(self):
        from qc_tool.vector.layer_area import run_check
        # 20 x 10 m polygon (area 200 m2);
        self.cursor.execute("INSERT INTO vector_1 VALUES (1, 'A', ST_MakeEnvelope(0, 10, 20, 20, 3035));")

        # 5 x 5 m polygon (area 25 m2);
        self.cursor.execute("INSERT INTO vector_1 VALUES (1, 'A', ST_MakeEnvelope(0, 5, 5, 10, 3035));")

        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)

    def test_warning(self):
        from qc_tool.vector.layer_area import run_check
        # 20 x 10 m polygon (area 200 m2);
        self.cursor.execute("INSERT INTO vector_1 VALUES (1, 'A', ST_MakeEnvelope(0, 10, 20, 20, 3035));")

        # 5 x 9.98 m polygon (area 49.9 m2);
        self.cursor.execute("INSERT INTO vector_1 VALUES (1, 'A', ST_MakeEnvelope(0, 5, 10, 9.98, 3035));")

        status = self.status_class()
        run_check(self.params, status)
        # We expect ok status and one warning message.
        self.assertEqual("ok", status.status)
        self.assertEqual(1, len(status.messages))


@skipIf(CONFIG["skip_inspire_check"], "INSPIRE check has been disabled.")
class Test_inspire(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.xml_dir = TEST_DATA_DIR.joinpath("metadata")
        self.params["unzip_dir"] = self.xml_dir
        self.params["tmp_dir"] = self.params["jobdir_manager"].tmp_dir
        self.params["output_dir"] = self.params["jobdir_manager"].output_dir
        self.params["layers"] = ["layer0"]
        self.params["step_nr"] = 1

    def test(self):
        from qc_tool.vector.inspire import run_check
        self.params["layer_defs"] = {"layer0": {"src_filepath": self.xml_dir.joinpath("inspire_good.gdb")}}
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.assertIn("s01_inspire_good_inspire_report.html", status.attachment_filenames)
        self.assertIn("s01_inspire_good_inspire_log.txt", status.attachment_filenames)

    def test_missing_xml(self):
        from qc_tool.vector.inspire import run_check
        self.params["layer_defs"] = {"layer0": {"src_filepath": self.xml_dir.joinpath("inspire_missing_xml.gdb")}}
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_xml_format(self):
        from qc_tool.vector.inspire import run_check
        self.params["layer_defs"] = {"layer0": {"src_filepath": self.xml_dir.joinpath("inspire_invalid_xml.gdb")}}
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.assertEqual(2, len(status.messages))
        self.assertIn("The xml file inspire_invalid_xml.xml does not contain a <gmd:MD_Metadata> top-level element.",
                      status.messages[1])

    def test_metadata_validation_failed(self):
        from qc_tool.vector.inspire import run_check
        self.params["layer_defs"] = {"layer0": {"src_filepath": self.xml_dir.joinpath("inspire_bad.gdb")}}
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.assertIn("s01_inspire_bad_inspire_report.html", status.attachment_filenames)
        self.assertIn("s01_inspire_bad_inspire_log.txt", status.attachment_filenames)
