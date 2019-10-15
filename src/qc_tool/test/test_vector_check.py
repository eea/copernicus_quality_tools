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
        self.params["filepath"] = TEST_DATA_DIR.joinpath("vector", "ua", "shp", "EE003L1_NARVA_UA2012.shp.zip")
        status = self.status_class()
        run_check(self.params, status)

        self.assertIn("unzip_dir", status.params)
        self.assertEqual("ok", status.status)

        unzip_dir = status.params["unzip_dir"]
        unzipped_subdir_names = [path.name for path in unzip_dir.glob("**")]
        unzipped_file_names = [path.name for path in unzip_dir.glob("**/*") if path.is_file()]

        self.assertIn("EE003L1_NARVA_UA2012.shp", unzipped_file_names,
                      "Unzipped directory should contain a file EE003L1_NARVA_UA2012.shp.")

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
        self.params.update({"layer_names": {"rpz": "^rpz_du(?P<aoi_code>[0-9]{3})[a-z]_lclu(?P<reference_year>[0-9]{4})_v[0-9]{2}$"},
                            "formats": [".shp"],
                            "aoi_codes": ["007"],
                            "boundary_source": "boundary_rpz.shp"})
        status = self.status_class()
        run_check(self.params, status)

        self.assertEqual("ok", status.status)
        self.assertEqual("rpz_DU007T_lclu2012_v01.shp", status.params["layer_defs"]["rpz"]["src_filepath"].name)
        self.assertEqual("rpz_DU007T_lclu2012_v01", status.params["layer_defs"]["rpz"]["src_layer_name"])
        self.assertEqual("boundary_rpz.shp", status.params["layer_defs"]["boundary"]["src_filepath"].name)
        self.assertEqual("boundary_rpz", status.params["layer_defs"]["boundary"]["src_layer_name"])


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


class Test_naming_ua_shp(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        from qc_tool.vector.unzip import run_check as unzip_check
        self.params.update({"tmp_dir": self.params["jobdir_manager"].tmp_dir,
                            "filepath": TEST_DATA_DIR.joinpath("vector", "ua", "shp", "EE003L1_NARVA_UA2012.shp.zip")})
        status = self.status_class()
        unzip_check(self.params, status)
        self.params["unzip_dir"] = status.params["unzip_dir"]
        self.params.update({"reference_year": "2012",
                            "formats": [".shp"],
                            "layer_names": {"reference": "_ua2012$"}})

    def test(self):
        from qc_tool.vector.naming import run_check
        status = self.status_class()
        run_check(self.params, status)

        self.assertEqual("ok", status.status)
        self.assertEqual(1, len(status.params["layer_defs"]))
        self.assertEqual("EE003L1_NARVA_UA2012.shp", status.params["layer_defs"]["reference"]["src_filepath"].name)
        self.assertEqual("EE003L1_NARVA_UA2012", status.params["layer_defs"]["reference"]["src_layer_name"])


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


class Test_epsg_shp(VectorCheckTestCase):
    def test(self):
        # Unzip the datasource.
        from qc_tool.vector.unzip import run_check as unzip_check
        zip_filepath = TEST_DATA_DIR.joinpath("vector", "ua", "shp", "EE003L1_NARVA_UA2012.shp.zip")
        self.params.update({"tmp_dir": self.params["jobdir_manager"].tmp_dir,
                            "filepath": zip_filepath})
        status = self.status_class()
        unzip_check(self.params, status)
        self.params["unzip_dir"] = status.params["unzip_dir"]

        # Run the check.
        from qc_tool.vector.epsg import run_check
        reference_path = self.params["unzip_dir"].joinpath("EE003L1_NARVA_UA2012.shp")
        self.params.update({"layer_defs": {"reference": {"src_filepath": reference_path,
                                                         "src_layer_name": reference_path.stem}},
                            "layers": ["reference"],
                            "epsg": 3035,
                            "auto_identify_epsg": True})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)


class Test_epsg_auto_identify_epsg(VectorCheckTestCase):
    def test(self):
        from qc_tool.vector.epsg import run_check
        boundary_path = TEST_DATA_DIR.joinpath("vector", "ua", "shp", "ES031L1_LUGO", "ES031L1_LUGO_UA2012_old.shp")
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
                                                       "src_layer_name": "clc06_mt"},
                                           "layer_1": {"src_filepath": gdb_dir,
                                                       "src_layer_name": "clc12_mt"}},
                            "layers": ["layer_0", "layer_1"]})
        status = self.status_class()
        run_check(self.params, status)

        self.assertEqual("ok", status.status)
        self.assertEqual("clc06_mt", self.params["layer_defs"]["layer_0"]["pg_layer_name"])
        self.assertEqual("objectid", self.params["layer_defs"]["layer_0"]["pg_fid_name"])
        self.assertEqual("clc12_mt", self.params["layer_defs"]["layer_1"]["pg_layer_name"])
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
                                                       "src_layer_name": "irrelevant_layer"}},
                            "layers": ["layer_0"]})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status)

    def test_precision(self):
        """ogr2ogr parameter PRECISION=NO should supress numeric field overflow error."""
        from qc_tool.vector.import2pg import run_check
        shp_filepath = TEST_DATA_DIR.joinpath("vector", "ua", "shp", "ES031L1_LUGO", "ES031L1_LUGO_UA2012_old.shp")
        self.params.update({"layer_defs": {"layer_0": {"src_filepath": shp_filepath,
                                                       "src_layer_name": "ES031L1_LUGO_UA2012_old"}},
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
        self.assertEqual("failed", status.status)


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
        self.assertEqual("failed", status.status)

    def test_self_intersecting_ring_fails(self):
        from qc_tool.vector.geometry import run_check
        self.cursor.execute("INSERT INTO test_layer VALUES (2, ST_PolygonFromText('POLYGON((0 0, 1 0, 0 1, 1 1, 0 0))', 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)


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
        self.cursor.execute("INSERT INTO boundary VALUES (ST_Difference(ST_MakeEnvelope(2, 2, 5, 5, 4326), ST_MakeEnvelope(3, 3, 4, 4, 4326)));")
        self.cursor.execute("CREATE TABLE reference (geom geometry(Polygon, 4326));")
        self.params.update({"layer_defs": {"reference": {"pg_layer_name": "reference"},
                                           "boundary": {"pg_layer_name": "boundary"}},
                            "layers": ["reference"],
                            "step_nr": 1})

    def test(self):
        from qc_tool.vector.gap import run_check
        self.cursor.execute("INSERT INTO reference VALUES (ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        self.cursor.execute("INSERT INTO reference VALUES (ST_MakeEnvelope(2, 2, 4, 5, 4326));")
        self.cursor.execute("INSERT INTO reference VALUES (ST_MakeEnvelope(4, 2, 5, 5, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.cursor.execute("SELECT * FROM s01_reference_gap_warning;")
        self.assertEqual(0, self.cursor.rowcount)

    def test_gap_warning(self):
        from qc_tool.vector.gap import run_check
        self.cursor.execute("INSERT INTO reference VALUES (ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.assertIn("gap", status.messages[0])
        self.cursor.execute("SELECT * FROM s01_reference_gap_warning;")
        self.assertEqual(1, self.cursor.rowcount)


class Test_gap_unit(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.cursor = self.params["connection_manager"].get_connection().cursor()
        self.cursor.execute("CREATE TABLE boundary (unit CHAR(1), geom geometry(Polygon, 4326));")
        self.cursor.execute("INSERT INTO boundary VALUES ('A', ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        self.cursor.execute("INSERT INTO boundary VALUES ('A', ST_Difference(ST_MakeEnvelope(2, 2, 5, 5, 4326), ST_MakeEnvelope(3, 3, 4, 4, 4326)));")
        self.cursor.execute("INSERT INTO boundary VALUES ('B', ST_MakeEnvelope(6, 6, 7, 7, 4326));")
        self.cursor.execute("INSERT INTO boundary VALUES ('B', ST_MakeEnvelope(8, 8, 9, 9, 4326));")
        self.cursor.execute("INSERT INTO boundary VALUES ('C', ST_MakeEnvelope(10, 10, 11, 11, 4326));")
        self.cursor.execute("CREATE TABLE reference (unit CHAR(1), geom geometry(Polygon, 4326));")
        self.params.update({"layer_defs": {"reference": {"pg_layer_name": "reference"},
                                           "boundary": {"pg_layer_name": "boundary"}},
                            "layers": ["reference"],
                            "boundary_unit_column_name": "unit",
                            "step_nr": 1})

    def test(self):
        from qc_tool.vector.gap_unit import run_check
        self.cursor.execute("INSERT INTO reference VALUES ('A', ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        self.cursor.execute("INSERT INTO reference VALUES ('A', ST_MakeEnvelope(2, 2, 4, 5, 4326));")
        self.cursor.execute("INSERT INTO reference VALUES ('A', ST_MakeEnvelope(4, 2, 5, 5, 4326));")
        self.cursor.execute("INSERT INTO reference VALUES ('B', ST_MakeEnvelope(6, 6, 9, 9, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.cursor.execute("SELECT * FROM s01_reference_gap_warning;")
        self.assertEqual(0, self.cursor.rowcount)

    def test_gap_warning(self):
        from qc_tool.vector.gap_unit import run_check
        self.cursor.execute("INSERT INTO reference VALUES ('A', ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        self.cursor.execute("INSERT INTO reference VALUES ('A', ST_MakeEnvelope(2, 2, 5, 5, 4326));")
        self.cursor.execute("INSERT INTO reference VALUES ('B', ST_MakeEnvelope(6, 6, 7, 7, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.assertIn("gap", status.messages[0])
        self.cursor.execute("SELECT * FROM s01_reference_gap_warning;")
        self.assertEqual(1, self.cursor.rowcount)

    def test_unit_warning(self):
        from qc_tool.vector.gap_unit import run_check
        self.cursor.execute("INSERT INTO reference VALUES ('D', ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        self.cursor.execute("INSERT INTO reference VALUES (NULL, ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.cursor.execute("SELECT * FROM s01_reference_unit_warning;")
        self.assertEqual(2, self.cursor.rowcount)

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
                            "code_column_name": "code",
                            "filter_code": "code2",
                            "area_column_name": "shape_area",
                            "mxmu": 500000,
                            "step_nr": 1})
        run_check(self.params, self.status_class())
        cursor.execute("SELECT fid FROM s01_reference_error ORDER BY fid;")
        self.assertListEqual([(31,)], cursor.fetchall())

class Test_mmu_clc_status(VectorCheckTestCase):
    def test(self):
        from qc_tool.vector.mmu_clc_status import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE reference (fid integer, code_12 varchar, shape_area real, geom geometry(Polygon, 4326));")

        # General features.
        cursor.execute("INSERT INTO reference VALUES (10, 'code1', 250001, ST_MakeEnvelope(10, 1, 11, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (12, 'code2', 250000, ST_MakeEnvelope(12, 0, 13, 2, 4326));")
        # Exception feature being at the boundary.
        cursor.execute("INSERT INTO reference VALUES (20, 'code3', 249999, ST_MakeEnvelope(20, 0, 21, 2, 4326));")
        # Error feature.
        cursor.execute("INSERT INTO reference VALUES (30, 'code3', 249999, ST_MakeEnvelope(10.1, 1.1, 10.9, 1.9, 4326));")

        self.params.update({"layer_defs": {"reference": {"pg_layer_name": "reference",
                                                         "pg_fid_name": "fid",
                                                         "fid_display_name": "row number"}},
                            "layers": ["reference"],
                            "code_column_name": "code_12",
                            "area_column_name": "shape_area",
                            "mmu": 250000,
                            "step_nr": 1})
        run_check(self.params, self.status_class())
        cursor.execute("SELECT fid FROM s01_reference_general ORDER BY fid;")
        self.assertListEqual([(10,), (12,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM s01_reference_exception ORDER BY fid;")
        self.assertListEqual([(20,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM s01_reference_error ORDER BY fid;")
        self.assertListEqual([(30,)], cursor.fetchall())

class Test_mmu(VectorCheckTestCase):
    def test(self):
        from qc_tool.vector.mmu import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE reference (fid integer, code varchar, shape_area real, geom geometry(Polygon, 4326));")

        # General features, class 1.
        cursor.execute("INSERT INTO reference VALUES (10, 'code1', 250001, ST_MakeEnvelope(10, 1, 11, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (12, 'code1', 250000, ST_MakeEnvelope(12, 0, 13, 2, 4326));")

        # General features, class 2.
        cursor.execute("INSERT INTO reference VALUES (14, 'code2', 500001, ST_MakeEnvelope(14, 1, 15, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (16, 'code2', 500000, ST_MakeEnvelope(16, 0, 17, 2, 4326));")

        # Excluded feature.
        cursor.execute("INSERT INTO reference VALUES (30, 'code1', 249999, ST_MakeEnvelope(10.1, 1.1, 10.9, 1.9, 4326));")

        # Error feature.
        cursor.execute("INSERT INTO reference VALUES (31, 'code2', 499999, ST_MakeEnvelope(14.1, 1.1, 14.9, 1.9, 4326));")

        self.params.update({"layer_defs": {"reference": {"pg_layer_name": "reference",
                                                         "pg_fid_name": "fid",
                                                         "fid_display_name": "row number"}},
                            "layers": ["reference"],
                            "code_column_name": "code",
                            "filter_code": "code2",
                            "area_column_name": "shape_area",
                            "mmu": 500000,
                            "step_nr": 1})
        run_check(self.params, self.status_class())
        cursor.execute("SELECT fid FROM s01_reference_error ORDER BY fid;")
        self.assertListEqual([(31,)], cursor.fetchall())


class Test_mmu_clc_change(VectorCheckTestCase):
    def test(self):
        from qc_tool.vector.mmu_clc_change import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()

        # Artificial margin.
        cursor.execute("CREATE TABLE margin (geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO margin VALUES (ST_MakeEnvelope(-1, -1, 100, 100, 4326));")

        # Add layer to be checked.
        cursor.execute("CREATE TABLE change (fid integer, shape_area real, code1 char(1), code2 char(1), geom geometry(Polygon, 4326));")

        # General features.
        cursor.execute("INSERT INTO change VALUES (10, 50001, 'X', 'X', ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        cursor.execute("INSERT INTO change VALUES (12, 50000, 'X', 'X', ST_MakeEnvelope(0, 2, 1, 3, 4326));")
        # General features at margin.
        cursor.execute("INSERT INTO change VALUES (14, 50001, 'X', 'X', ST_MakeEnvelope(-1, 4, 1, 5, 4326));")
        cursor.execute("INSERT INTO change VALUES (16, 50000, 'X', 'X', ST_MakeEnvelope(-1, 6, 1, 7, 4326));")
        # Exception feature at margin.
        cursor.execute("INSERT INTO change VALUES (20, 49999, 'X', 'X', ST_MakeEnvelope(-1, 8, 1, 9, 4326));")
        # Exception pair of features taking part in complex change with the same code in initial year.
        cursor.execute("INSERT INTO change VALUES (22, 40000, 'A', '1', ST_MakeEnvelope(0, 10, 1, 11, 4326));")
        cursor.execute("INSERT INTO change VALUES (23, 10000, 'A', '2', ST_MakeEnvelope(1, 10, 2, 11, 4326));")
        # Exception pair of features taking part in complex change with the same code in final year.
        cursor.execute("INSERT INTO change VALUES (25, 40000, '1', 'B', ST_MakeEnvelope(0, 12, 1, 13, 4326));")
        cursor.execute("INSERT INTO change VALUES (26, 10000, '2', 'B', ST_MakeEnvelope(1, 12, 2, 13, 4326));")
        # Error feature.
        cursor.execute("INSERT INTO change VALUES (30, 49999, 'C', 'C', ST_MakeEnvelope(0, 14, 1, 15, 4326));")
        # Error feature, complex change with total area below limit.
        cursor.execute("INSERT INTO change VALUES (32, 40000, '1', 'D', ST_MakeEnvelope(0, 16, 1, 17, 4326));")
        cursor.execute("INSERT INTO change VALUES (33,  9999, '2', 'D', ST_MakeEnvelope(1, 16, 2, 17, 4326));")

        self.params.update({"layer_defs": {"change": {"pg_layer_name": "change",
                                                      "pg_fid_name": "fid",
                                                      "fid_display_name": "row number"},
                                           "reference": {"pg_layer_name": "margin"}},
                            "layers": ["change"],
                            "initial_code_column_name": "code1",
                            "final_code_column_name": "code2",
                            "area_column_name": "shape_area",
                            "mmu": 50000,
                            "step_nr": 1})
        run_check(self.params, self.status_class())
        cursor.execute("SELECT * FROM s01_change_general ORDER BY fid;")
        self.assertListEqual([(10,), (12,), (14,), (16,)], cursor.fetchall())
        cursor.execute("SELECT * FROM s01_change_exception ORDER BY fid;")
        self.assertListEqual([(20,), (22,), (23,), (25,), (26,)], cursor.fetchall())
        cursor.execute("SELECT * FROM s01_change_error ORDER BY fid;")
        self.assertListEqual([(30,), (32,), (33,)], cursor.fetchall())


class Test_mmu_ua_status(VectorCheckTestCase):
    def test(self):
        from qc_tool.vector.mmu_ua_status import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE reference (fid integer, shape_area real, code char(5), geom geometry(Polygon, 4326));")

        # General features.
        cursor.execute("INSERT INTO reference VALUES (10, 1, '122', ST_MakeEnvelope(10, 1, 11, 8, 4326));")
        cursor.execute("INSERT INTO reference VALUES (12, 1, '1228', ST_MakeEnvelope(12, 1, 13, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (14, 1, '12288', ST_MakeEnvelope(14, 1, 15, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (16, 1, '1228', ST_MakeEnvelope(16, 1, 17, 2, 4326));")

        cursor.execute("INSERT INTO reference VALUES (18, 2501, '1', ST_MakeEnvelope(10, 8, 19, 10, 4326));")
        cursor.execute("INSERT INTO reference VALUES (20, 2500, '1', ST_MakeEnvelope(20, 1, 21, 2, 4326));")

        cursor.execute("INSERT INTO reference VALUES (22, 10000, '2', ST_MakeEnvelope(59, 0, 80, 3, 4326));")
        cursor.execute("INSERT INTO reference VALUES (24, 10000, '3', ST_MakeEnvelope(24, 1, 25, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (26, 10000, '4', ST_MakeEnvelope(26, 1, 27, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (28, 10000, '5', ST_MakeEnvelope(28, 1, 29, 2, 4326));")

        cursor.execute("INSERT INTO reference VALUES (30, 1, '9', ST_MakeEnvelope(30, 1, 31, 4, 4326));")

        # Exception features, touches fid=30.
        cursor.execute("INSERT INTO reference VALUES (40, 1, '2', ST_MakeEnvelope(31, 3, 41, 4, 4326));")

        # Exception feature at margin.
        cursor.execute("INSERT INTO reference VALUES (42, 100, '2', ST_MakeEnvelope(42, 0, 43, 4, 4326));")

        # Warning feature, touches fid=10.
        cursor.execute("INSERT INTO reference VALUES (50, 500, '2', ST_MakeEnvelope(10.1, 8, 11, 9, 4326));")

        # Error features breaking general requirements.
        cursor.execute("INSERT INTO reference VALUES (60, 1, '123', ST_MakeEnvelope(60, 1, 61, 2, 4326));")

        cursor.execute("INSERT INTO reference VALUES (62, 2499, '1', ST_MakeEnvelope(63, 1, 63, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (64, 2499, '13', ST_MakeEnvelope(65, 1, 65, 2, 4326));")

        cursor.execute("INSERT INTO reference VALUES (66, 9999, '2', ST_MakeEnvelope(67, 1, 67, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (68, 9999, '3', ST_MakeEnvelope(69, 1, 69, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (70, 9999, '4', ST_MakeEnvelope(71, 1, 71, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (72, 9999, '5', ST_MakeEnvelope(73, 1, 73, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (74, 20000, '6', ST_MakeEnvelope(75, 1, 75, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (76, 20000, '7', ST_MakeEnvelope(77, 1, 77, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (78, 20000, '8', ST_MakeEnvelope(79, 1, 79, 2, 4326));")

        # Error feature breaking exception requirements.
        cursor.execute("INSERT INTO reference VALUES (80, 99, '4', ST_MakeEnvelope(80, 0, 81, 2, 4326));")

        # Error feature breaking warning requirements, touches fid=10.
        cursor.execute("INSERT INTO reference VALUES (82, 499, '2', ST_MakeEnvelope(10.1, 8, 11, 9, 4326));")

        self.params.update({"layer_defs": {"reference": {"pg_layer_name": "reference",
                                                         "pg_fid_name": "fid",
                                                         "fid_display_name": "row number"}},
                            "layers": ["reference"],
                            "area_column_name": "shape_area",
                            "code_column_name": "code",
                            "step_nr": 1})
        run_check(self.params, self.status_class())
        cursor.execute("SELECT fid FROM s01_reference_general ORDER BY fid;")
        self.assertListEqual([(10,), (12,), (14,), (16,), (18,), (20,), (22,), (24,), (26,), (28,), (30,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM s01_reference_exception ORDER BY fid;")
        self.assertListEqual([(40,), (42,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM s01_reference_warning ORDER BY fid;")
        self.assertListEqual([(50,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM s01_reference_error ORDER BY fid;")
        self.assertListEqual([(60,), (62,), (64,), (66,), (68,), (70,), (72,), (74,), (76,), (78,), (80,), (82,)], cursor.fetchall())


class Test_mmu_ua_change(VectorCheckTestCase):
    def test(self):
        from qc_tool.vector.mmu_ua_change import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE change (fid integer, shape_area real, code1 char(5), code2 char(5), geom geometry(Polygon, 4326));")

        # General features.
        cursor.execute("INSERT INTO change VALUES (10, 1001, 'X', '1', ST_MakeEnvelope(10, 1, 11, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (12, 1000, 'X', '1', ST_MakeEnvelope(12, 1, 13, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (14, 1000, 'X', '12', ST_MakeEnvelope(14, 1, 15, 2, 4326));")

        cursor.execute("INSERT INTO change VALUES (16, 2500, 'X', '2', ST_MakeEnvelope(16, 1, 17, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (18, 2500, 'X', '3', ST_MakeEnvelope(18, 1, 19, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (20, 2500, 'X', '4', ST_MakeEnvelope(20, 1, 21, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (22, 2500, 'X', '5', ST_MakeEnvelope(22, 1, 23, 2, 4326));")

        # Exception features.
        cursor.execute("INSERT INTO change VALUES (30, 1, '122', 'X', ST_MakeEnvelope(30, 1, 31, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (32, 1, 'X', '122', ST_MakeEnvelope(32, 1, 33, 2, 4326));")

        # Error features breaking general requirements.
        cursor.execute("INSERT INTO change VALUES (40, 999, 'X', '1', ST_MakeEnvelope(40, 1, 11, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (42, 999, 'X', '12', ST_MakeEnvelope(42, 1, 11, 2, 4326));")

        cursor.execute("INSERT INTO change VALUES (44, 2499, 'X', '2', ST_MakeEnvelope(44, 1, 45, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (46, 2499, 'X', '3', ST_MakeEnvelope(46, 1, 46, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (48, 2499, 'X', '4', ST_MakeEnvelope(48, 1, 48, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (50, 2499, 'X', '5', ST_MakeEnvelope(50, 1, 50, 2, 4326));")

        cursor.execute("INSERT INTO change VALUES (52, 20000, 'X', '6', ST_MakeEnvelope(52, 1, 53, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (54, 20000, 'X', '7', ST_MakeEnvelope(54, 1, 55, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (56, 20000, 'X', '8', ST_MakeEnvelope(56, 1, 57, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (58, 20000, 'X', '9', ST_MakeEnvelope(58, 1, 59, 2, 4326));")

        # Error features breaking exception requirements.
        cursor.execute("INSERT INTO change VALUES (60, 1, '123', 'X', ST_MakeEnvelope(12, 1, 13, 2, 4326));")
        cursor.execute("INSERT INTO change VALUES (62, 1, 'X', '123', ST_MakeEnvelope(12, 1, 13, 2, 4326));")

        self.params.update({"layer_defs": {"change": {"pg_layer_name": "change",
                                                      "pg_fid_name": "fid",
                                                      "fid_display_name": "row number"}},
                            "layers": ["change"],
                            "area_column_name": "shape_area",
                            "initial_code_column_name": "code1",
                            "final_code_column_name": "code2",
                            "step_nr": 1})
        run_check(self.params, self.status_class())
        cursor.execute("SELECT fid FROM s01_change_general ORDER BY fid;")
        self.assertListEqual([(10,), (12,), (14,), (16,), (18,), (20,), (22,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM s01_change_exception ORDER BY fid;")
        self.assertListEqual([(30,), (32,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM s01_change_error ORDER BY fid;")
        self.assertListEqual([(40,), (42,), (44,), (46,), (48,), (50,), (52,), (54,), (56,), (58,), (60,), (62,)], cursor.fetchall())


class Test_mmu_n2k(VectorCheckTestCase):
    def test(self):
        from qc_tool.vector.mmu_n2k import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE n2k (fid integer, area_ha real, code integer, geom geometry(Polygon, 4326));")

        # Artificial margin as a general feature.
        cursor.execute("INSERT INTO n2k VALUES (0, 0.5, 10, ST_MakeEnvelope(-1, -1, 100, 100, 4326));")

        # Marginal features.
        cursor.execute("INSERT INTO n2k VALUES (10, 0.1, 8, ST_MakeEnvelope(-1, 0, 1, 1, 4326));")
        cursor.execute("INSERT INTO n2k VALUES (11, 0.0999, 8, ST_MakeEnvelope(-1, 2, 1, 3, 4326));")

        # Linear features.
        cursor.execute("INSERT INTO n2k VALUES (20, 0.1, 121, ST_MakeEnvelope(0, 4, 1, 5, 4326));")
        cursor.execute("INSERT INTO n2k VALUES (21, 0.1, 1211, ST_MakeEnvelope(0, 6, 1, 7, 4326));")
        cursor.execute("INSERT INTO n2k VALUES (22, 0.1, 122, ST_MakeEnvelope(0, 8, 1, 9, 4326));")
        cursor.execute("INSERT INTO n2k VALUES (23, 0.1, 911, ST_MakeEnvelope(0, 10, 1, 11, 4326));")
        cursor.execute("INSERT INTO n2k VALUES (24, 0.1, 912, ST_MakeEnvelope(0, 12, 1, 13, 4326));")
        cursor.execute("INSERT INTO n2k VALUES (25, 0.0999, 121, ST_MakeEnvelope(0, 14, 1, 15, 4326));")

        # Urban feature touching road or railway.
        cursor.execute("INSERT INTO n2k VALUES (30, 0.25, 1, ST_MakeEnvelope(1, 14, 2, 15, 4326));")

        # Complex change features.
        cursor.execute("INSERT INTO n2k VALUES (40, 0.2, 9, ST_MakeEnvelope(0, 16, 1, 17, 4326));")
        cursor.execute("INSERT INTO n2k VALUES (41, 0.2, 9, ST_MakeEnvelope(1, 16, 2, 17, 4326));")
        cursor.execute("INSERT INTO n2k VALUES (42, 0.2, 9, ST_MakeEnvelope(2, 16, 3, 17, 4326));")

        self.params.update({"layer_defs": {"n2k": {"pg_layer_name": "n2k",
                                                   "pg_fid_name": "fid",
                                                   "fid_display_name": "row number"}},
                            "layers": ["n2k"],
                            "area_column_name": "area_ha",
                            "area_ha": 0.5,
                            "initial_code_column_name": "code",
                            "final_code_column_name": "code",
                            "step_nr": 1})
        run_check(self.params, self.status_class())
        cursor.execute("SELECT fid FROM s01_n2k_general ORDER BY fid;")
        self.assertListEqual([(0,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM s01_n2k_exception ORDER BY fid;")
        self.assertListEqual([(10,), (20,), (21,), (22,), (23,), (24,), (30,), (40,), (41,), (42,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM s01_n2k_error ORDER BY fid;")
        self.assertListEqual([(11,), (25,)], cursor.fetchall())


class Test_mmu_rpz(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.cursor = self.params["connection_manager"].get_connection().cursor()
        self.cursor.execute("CREATE TABLE rpz (fid integer, area_ha real, code integer, ua char(1), comment varchar(40), geom geometry(Polygon, 4326));")

        # Artificial margin as a general feature.
        self.cursor.execute("INSERT INTO rpz VALUES (0, 0.5, 10, NULL, NULL, ST_MakeEnvelope(-1, -1, 50, 50, 4326));")

        # Feature being part of Urban Atlas Core Region.
        self.cursor.execute("INSERT INTO rpz VALUES (1, 0.01, 1, 'U', NULL, ST_MakeEnvelope(50, -1, 51, 50, 4326));")

        # Marginal features.
        self.cursor.execute("INSERT INTO rpz VALUES (10, 0.2, 8, NULL, NULL, ST_MakeEnvelope(-1, 0, 1, 1, 4326));")
        self.cursor.execute("INSERT INTO rpz VALUES (11, 0.19, 8, NULL, NULL, ST_MakeEnvelope(-1, 2, 1, 3, 4326));")

        # Marginal features touching Urban Atlas Core Region.
        self.cursor.execute("INSERT INTO rpz VALUES (12, 0.2, 8, NULL, NULL, ST_MakeEnvelope(49, 0, 50, 1, 4326));")
        self.cursor.execute("INSERT INTO rpz VALUES (13, 0.19, 8, NULL, NULL, ST_MakeEnvelope(49, 2, 50, 3, 4326))")

        # Urban features.
        self.cursor.execute("INSERT INTO rpz VALUES (20, 0.25, 1111, NULL, NULL, ST_MakeEnvelope(2, 0, 3, 1, 4326));")
        self.cursor.execute("INSERT INTO rpz VALUES (21, 0.24, 1111, NULL, NULL, ST_MakeEnvelope(2, 1, 3, 2, 4326))")
        self.cursor.execute("INSERT INTO rpz VALUES (22, 0.25, 1112, NULL, NULL, ST_MakeEnvelope(2, 2, 3, 3, 4326));")
        self.cursor.execute("INSERT INTO rpz VALUES (23, 0.24, 1112, NULL, NULL, ST_MakeEnvelope(2, 3, 3, 4, 4326))")
        self.cursor.execute("INSERT INTO rpz VALUES (24, 0.25, 1113, NULL, NULL, ST_MakeEnvelope(2, 4, 3, 5, 4326));")
        self.cursor.execute("INSERT INTO rpz VALUES (25, 0.24, 1113, NULL, NULL, ST_MakeEnvelope(2, 5, 3, 6, 4326))")

        # Linear features.
        self.cursor.execute("INSERT INTO rpz VALUES (30, 0.1,  1210, NULL, NULL, ST_MakeEnvelope(4, 0, 5, 1, 4326));")
        self.cursor.execute("INSERT INTO rpz VALUES (31, 0.09, 1210, NULL, NULL, ST_MakeEnvelope(4, 1, 5, 2, 4326));")
        self.cursor.execute("INSERT INTO rpz VALUES (32, 0.1,  1220, NULL, NULL, ST_MakeEnvelope(4, 2, 5, 3, 4326));")
        self.cursor.execute("INSERT INTO rpz VALUES (33, 0.09, 1220, NULL, NULL, ST_MakeEnvelope(4, 3, 5, 4, 4326));")
        self.cursor.execute("INSERT INTO rpz VALUES (34, 0.1,  1230, NULL, NULL, ST_MakeEnvelope(4, 4, 5, 5, 4326));")
        self.cursor.execute("INSERT INTO rpz VALUES (35, 0.09, 1230, NULL, NULL, ST_MakeEnvelope(4, 5, 5, 6, 4326));")

        # Features with specific comment.
        self.cursor.execute("INSERT INTO rpz VALUES (40, 0, 8, NULL, 'comment1', ST_MakeEnvelope(6, 0, 7, 1, 4326));")
        self.cursor.execute("INSERT INTO rpz VALUES (41, 0, 8, NULL, 'comment1 nok', ST_MakeEnvelope(6, 0, 7, 1, 4326));")

        self.params.update({"layer_defs": {"rpz": {"pg_layer_name": "rpz",
                                                   "pg_fid_name": "fid",
                                                   "fid_display_name": "row number"}},
                            "layers": ["rpz"],
                            "area_column_name": "area_ha",
                            "area_ha": 0.5,
                            "code_column_name": "code",
                            "urban_feature_codes": [1111, 1112],
                            "linear_feature_codes": [1210, 1220],
                            "exception_comments": ["comment1"],
                            "step_nr": 1})

    def test(self):
        from qc_tool.vector.mmu_rpz import run_check
        run_check(self.params, self.status_class())
        self.cursor.execute("SELECT fid FROM s01_rpz_general ORDER BY fid;")
        self.assertListEqual([(0,), (1,)], self.cursor.fetchall())
        self.cursor.execute("SELECT fid FROM s01_rpz_exception ORDER BY fid;")
        self.assertListEqual([(10,), (12,), (20,), (22,), (30,), (32,), (40,)], self.cursor.fetchall())
        self.cursor.execute("SELECT fid FROM s01_rpz_error ORDER BY fid;")
        self.assertListEqual([(11,), (13,), (21,), (23,), (24,), (25,), (31,), (33,), (34,), (35,), (41,)], self.cursor.fetchall())

    def test_empty_codes(self):
        from qc_tool.vector.mmu_rpz import run_check
        self.params.update({"urban_feature_codes": [],
                            "linear_feature_codes": [],
                            "exception_comments": []})
        run_check(self.params, self.status_class())


class Test_mmw(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.params.update({"layer_defs": {"mmw": {"pg_layer_name": "mmw",
                                                   "pg_fid_name": "fid",
                                                   "fid_display_name": "row number"}},
                            "layers": ["mmw"],
                            "mmw": 1.0,
                            "step_nr": 1})

    def test(self):
        from qc_tool.vector.mmw import run_check
        self.params.update({"code_column_name": None,
                            "filter_code": None})
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
        self.params.update({"code_column_name": "code",
                            "filter_code": "2"})
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE mmw (fid integer, code char(1), geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO mmw VALUES (1, NULL, ST_MakeEnvelope(0, 0, 3, 0.999, 4326));")
        cursor.execute("INSERT INTO mmw VALUES (2, '1', ST_MakeEnvelope(0, 0, 3, 0.999, 4326));")
        cursor.execute("INSERT INTO mmw VALUES (3, '2', ST_MakeEnvelope(0, 0, 3, 0.999, 4326));")
        cursor.execute("INSERT INTO mmw VALUES (4, '2', ST_MakeEnvelope(0, 0, 3, 1.001, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        cursor.execute("SELECT fid FROM s01_mmw_warning ORDER BY fid;")
        self.assertListEqual([(3,)], cursor.fetchall())


class Test_mmw_ua(VectorCheckTestCase):
    def test(self):
        from qc_tool.vector.mmw_ua import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE mmw (fid integer, code char(5), geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO mmw VALUES (1, '12', ST_MakeEnvelope(10, 0, 13, 0.999, 4326));")
        cursor.execute("INSERT INTO mmw VALUES (2, '12', ST_MakeEnvelope(20, 0, 23, 1, 4326));")
        cursor.execute("INSERT INTO mmw VALUES (3, '12', ST_MakeEnvelope(30, 0, 33, 1.001, 4326));")
        cursor.execute("INSERT INTO mmw VALUES (4, '12', ST_Difference(ST_MakeEnvelope(40, 0, 49, 9, 4326),"
                                                                     " ST_MakeEnvelope(43, 0, 46, 8, 4326)));")
        cursor.execute("INSERT INTO mmw VALUES (5, '122', ST_MakeEnvelope(50, 0, 53, 1, 4326));")

        self.params.update({"layer_defs": {"mmw": {"pg_layer_name": "mmw",
                                                   "pg_fid_name": "fid",
                                                   "fid_display_name": "row number"}},
                            "layers": ["mmw"],
                            "code_column_name": "code",
                            "mmw": 1.0,
                            "step_nr": 1})
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
                            "code_column_name": "code",
                            "filter_code": "1",
                            "mxmw": 1.0,
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
    def test(self):
        from qc_tool.vector.mml import run_check
        self.params.update({"layer_defs": {"mml": {"pg_layer_name": "mml",
                                                   "pg_fid_name": "fid",
                                                   "fid_display_name": "row number"}},
                            "layers": ["mml"],
                            "code_column_name": "code",
                            "filter_code": "1",
                            "mml": 10.,
                            "step_nr": 1})
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE mml (fid integer, code char(1), geom geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO mml VALUES (1, NULL, ST_MakeEnvelope(0, 0, 5, 1, 4326));")
        cursor.execute("INSERT INTO mml VALUES (2, '1', ST_MakeEnvelope(0, 0, 5, 1, 4326));")
        cursor.execute("INSERT INTO mml VALUES (3, '1', ST_MakeEnvelope(0, 0, 9.999, 1, 4326));")
        cursor.execute("INSERT INTO mml VALUES (4, '1', ST_MakeEnvelope(0, 0, 10, 1, 4326));")
        cursor.execute("INSERT INTO mml VALUES (5, '1', ST_MakeEnvelope(0, 0, 11, 1, 4326));")
        cursor.execute("INSERT INTO mml VALUES (6, '2', ST_MakeEnvelope(0, 0, 5, 1, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        cursor.execute("SELECT fid FROM s01_mml_warning ORDER BY fid;")
        self.assertListEqual([(2,), (3,)], cursor.fetchall())


class Test_overlap(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.cursor = self.params["connection_manager"].get_connection().cursor()
        self.cursor.execute("CREATE TABLE test_layer_1 (fid integer, geom geometry(Polygon, 4326));")
        self.cursor.execute("CREATE TABLE test_layer_2 (fid integer, geom geometry(Polygon, 4326));")
        self.params.update({"layer_defs": {"layer_1": {"pg_layer_name": "test_layer_1",
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"},
                                           "layer_2": {"pg_layer_name": "test_layer_2",
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
                            "layers": ["layer_1", "layer_2"],
                            "step_nr": 1})

    def test_non_overlapping(self):
        from qc_tool.vector.overlap import run_check
        self.cursor.execute("INSERT INTO test_layer_1 VALUES (1, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                           " (2, ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                                                           " (3, ST_MakeEnvelope(3, 1, 4, 2, 4326)),"
                                                           " (4, ST_MakeEnvelope(4, 1, 5, 2, 4326));")
        self.cursor.execute("INSERT INTO test_layer_2 VALUES (1, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                           " (2, ST_MakeEnvelope(2, 0, 3, 1, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_overlapping_fails(self):
        from qc_tool.vector.overlap import run_check
        self.cursor.execute("INSERT INTO test_layer_1 VALUES (1, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                           " (5, ST_MakeEnvelope(0.9, 0, 2, 1, 4326));")
        self.cursor.execute("INSERT INTO test_layer_2 VALUES (1, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                           " (5, ST_MakeEnvelope(0.9, 0, 2, 1, 4326)),"
                                                           " (6, ST_MakeEnvelope(0.8, 0, 3, 1, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)
        self.cursor.execute("SELECT fid FROM s01_test_layer_1_error ORDER BY fid;")
        self.assertListEqual([(1,), (5,)], self.cursor.fetchall())
        self.cursor.execute("SELECT fid FROM s01_test_layer_2_error ORDER BY fid;")
        self.assertListEqual([(1,), (5,), (6,)], self.cursor.fetchall())


class Test_neighbour(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        from qc_tool.vector.neighbour import run_check
        self.run_check = run_check
        self.cursor = self.params["connection_manager"].get_connection().cursor()
        self.cursor.execute("CREATE TABLE test_layer (fid integer, attr_1 char(1), attr_2 char(1), geom geometry(Polygon, 4326));")
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "test_layer",
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
                            "layers": ["layer_0"],
                            "code_column_names": ["attr_1", "attr_2"],
                            "step_nr": 1})

    def test_disjoint(self):
        self.cursor.execute("INSERT INTO test_layer VALUES (1, 'A', 'A', ST_MakeEnvelope(1, 0, 2, 1, 4326)),"
                                                         " (2, 'A', 'A', ST_MakeEnvelope(3, 0, 4, 1, 4326));")
        status = self.status_class()
        self.run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_different_class(self):
        self.cursor.execute("INSERT INTO test_layer VALUES (1, 'A', 'A', ST_MakeEnvelope(1, 0, 2, 1, 4326)),"
                                                         " (2, 'B', 'B', ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                                                         " (3, 'C', 'B', ST_MakeEnvelope(3, 0, 4, 1, 4326)),"
                                                         " (4, 'C', 'C', ST_MakeEnvelope(4, 0, 5, 1, 4326));")
        status = self.status_class()
        self.run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_touching_point(self):
        self.cursor.execute("INSERT INTO test_layer VALUES (1, 'A', 'A', ST_MakeEnvelope(1, 0, 2, 1, 4326)),"
                                                         " (2, 'A', 'A', ST_MakeEnvelope(2, 1, 3, 2, 4326));")
        status = self.status_class()
        self.run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_touching_line_fails(self):
        self.cursor.execute("INSERT INTO test_layer VALUES (1, 'A', 'A', ST_MakeEnvelope(1, 0, 2, 1, 4326)),"
                                                         " (2, 'A', 'A', ST_MakeEnvelope(2, 0, 3, 1, 4326));")
        status = self.status_class()
        self.run_check(self.params, status)
        self.assertEqual("failed", status.status)

    def test_complex_geom_fails(self):
        polygon = "POLYGON((2 0, 2 0.5, 2.5 0.5, 2 1, 2 1.5, 2.5 1.5, 2 2, 2.5 2, 2 2.5, 2.5 2.5, 3 3, 3 0, 2 0))"
        create_sql = ("INSERT INTO test_layer VALUES (1, 'A', 'A', ST_MakeEnvelope(1, 0, 2, 3, 4326)),"
                                                   " (2, 'A', 'A', ST_PolygonFromText('" + polygon + "', 4326));")
        self.cursor.execute(create_sql)
        status = self.status_class()
        self.run_check(self.params, status)
        self.assertEqual("failed", status.status)

    def test_exclude(self):
        self.cursor.execute("INSERT INTO test_layer VALUES (1, 'A', 'A', ST_MakeEnvelope(1, 0, 2, 1, 4326)),"
                                                         " (2, 'A', 'A', ST_MakeEnvelope(2, 0, 3, 1, 4326));")
        self.params["exclude_codes"] = ["A", "C%"]
        status = self.status_class()
        self.run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_exclude_fails(self):
        self.cursor.execute("INSERT INTO test_layer VALUES (1, 'A', 'A', ST_MakeEnvelope(1, 0, 2, 1, 4326)),"
                                                         " (2, 'A', 'A', ST_MakeEnvelope(2, 0, 3, 1, 4326));")
        self.params["exclude_codes"] = ["B", "C%"]
        status = self.status_class()
        self.run_check(self.params, status)
        self.assertEqual("failed", status.status)

class Test_neighbour_technical(VectorCheckTestCase):
    """Test neighbouring polygons taking into account technical change."""
    def setUp(self):
        super().setUp()
        from qc_tool.vector.neighbour import run_check
        self.run_check = run_check
        self.cursor = self.params["connection_manager"].get_connection().cursor()
        self.cursor.execute("CREATE TABLE test_layer (fid integer, attr_1 char(1), attr_2 char(1), chtype char(1), geom geometry(Polygon, 4326));")
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "test_layer",
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
                            "layers": ["layer_0"],
                            "code_column_names": ["attr_1", "attr_2"],
                            "chtype_column_name": "chtype",
                            "step_nr": 1})

    def test_non_neighbouring(self):
        self.cursor.execute("INSERT INTO test_layer VALUES (1, 'A', 'A', 'R', ST_MakeEnvelope(1, 0, 1.5, 1, 4326)),"
                                                         " (2, 'A', 'A', 'R', ST_MakeEnvelope(2, 0, 2.5, 1, 4326)),"
                                                         " (3, 'A', 'A', 'R', ST_MakeEnvelope(3, 0, 3.5, 1, 4326));")
        status = self.status_class()
        self.run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_exception(self):
        self.cursor.execute("INSERT INTO test_layer VALUES (1, 'A', 'A', 'R', ST_MakeEnvelope(1, 0, 2, 1, 4326)),"
                                                         " (2, 'A', 'A', 'T', ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                                                         " (3, 'A', 'A', 'T', ST_MakeEnvelope(3, 0, 4, 1, 4326)),"
                                                         " (4, 'A', 'A', NULL, ST_MakeEnvelope(4, 0, 5, 1, 4326)),"
                                                         " (5, 'A', 'B', NULL, ST_MakeEnvelope(5, 0, 6, 1, 4326));")
        status = self.status_class()
        self.run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.cursor.execute("SELECT * FROM s01_test_layer_exception ORDER BY fid;")
        self.assertListEqual([(1,), (2,), (3,), (4,)], self.cursor.fetchall())
        self.cursor.execute("SELECT * FROM s01_test_layer_error ORDER BY fid;")
        self.assertListEqual([], self.cursor.fetchall())

    def test_error(self):
        self.cursor.execute("INSERT INTO test_layer VALUES (1, 'A', 'A', 'R', ST_MakeEnvelope(1, 0, 2, 1, 4326)),"
                                                         " (2, 'A', 'A', 'R', ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                                                         " (3, 'A', 'A', 'T', ST_MakeEnvelope(3, 0, 4, 1, 4326));")
        status = self.status_class()
        self.run_check(self.params, status)
        self.assertEqual("failed", status.status)
        self.cursor.execute("SELECT * FROM s01_test_layer_exception ORDER BY fid;")
        self.assertListEqual([(2,), (3,)], self.cursor.fetchall())
        self.cursor.execute("SELECT * FROM s01_test_layer_error ORDER BY fid;")
        self.assertListEqual([(1,), (2,)], self.cursor.fetchall())


class Test_neighbour_rpz(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.cursor = self.params["connection_manager"].get_connection().cursor()
        self.params.update({"layer_defs": {"rpz": {"pg_layer_name": "rpz_layer",
                                                   "pg_fid_name": "fid",
                                                   "fid_display_name": "row number"}},
                            "layers": ["rpz"],
                            "code_column_name": "code",
                            "exception_comments": ["Comment 1", "Comment 2"],
                            "step_nr": 1})
        self.cursor.execute("CREATE TABLE rpz_layer (fid integer, code char(1), ua char(1), comment varchar, geom geometry(Polygon, 4326));")

    def test(self):
        self.cursor.execute("INSERT INTO rpz_layer VALUES (1, 'A', 'U', NULL, ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        self.cursor.execute("INSERT INTO rpz_layer VALUES (2, 'A', 'U', NULL, ST_MakeEnvelope(1, 0, 2, 1, 4326));")
        self.cursor.execute("INSERT INTO rpz_layer VALUES (3, 'A', NULL, NULL, ST_MakeEnvelope(2, 0, 3, 1, 4326));")
        self.cursor.execute("INSERT INTO rpz_layer VALUES (4, 'B', NULL, NULL, ST_MakeEnvelope(3, 0, 4, 1, 4326));")
        self.cursor.execute("INSERT INTO rpz_layer VALUES (5, 'B', NULL, NULL, ST_MakeEnvelope(4, 0, 5, 1, 4326));")
        self.cursor.execute("INSERT INTO rpz_layer VALUES (6, 'C', NULL, NULL, ST_MakeEnvelope(5, 0, 6, 1, 4326));")

        from qc_tool.vector.neighbour_rpz import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)
        self.cursor.execute("SELECT fid FROM s01_rpz_layer_exception ORDER BY fid;")
        self.assertListEqual([], self.cursor.fetchall())
        self.cursor.execute("SELECT fid FROM s01_rpz_layer_error ORDER BY fid;")
        self.assertListEqual([(4,), (5,)], self.cursor.fetchall())

    def test_comments(self):
        self.cursor.execute("INSERT INTO rpz_layer VALUES (1, 'A', NULL, 'Comment 1', ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        self.cursor.execute("INSERT INTO rpz_layer VALUES (2, 'A', NULL, 'Comment 2', ST_MakeEnvelope(1, 0, 2, 1, 4326));")
        self.cursor.execute("INSERT INTO rpz_layer VALUES (3, 'A', NULL, 'Comment 1', ST_MakeEnvelope(2, 0, 3, 1, 4326));")
        self.cursor.execute("INSERT INTO rpz_layer VALUES (4, 'B', NULL, 'hu', ST_MakeEnvelope(3, 0, 4, 1, 4326));")
        self.cursor.execute("INSERT INTO rpz_layer VALUES (5, 'B', 'U', 'Comment 1', ST_MakeEnvelope(4, 0, 5, 1, 4326));")

        from qc_tool.vector.neighbour_rpz import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.cursor.execute("SELECT fid FROM s01_rpz_layer_exception ORDER BY fid;")
        self.assertListEqual([(1,), (2,), (3,)], self.cursor.fetchall())
        self.cursor.execute("SELECT fid FROM s01_rpz_layer_error ORDER BY fid;")
        self.assertListEqual([], self.cursor.fetchall())


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

    def test_missing_xml_fail(self):
        from qc_tool.vector.inspire import run_check
        self.params["layer_defs"] = {"layer0": {"src_filepath": self.xml_dir.joinpath("inspire_missing_xml.gdb")}}
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)

    def test_xml_format_fail(self):
        from qc_tool.vector.inspire import run_check
        self.params["layer_defs"] = {"layer0": {"src_filepath": self.xml_dir.joinpath("inspire_invalid_xml.gdb")}}
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)
        self.assertEqual(2, len(status.messages))
        self.assertIn("The xml file inspire_invalid_xml.xml does not contain a <gmd:MD_Metadata> top-level element.",
                      status.messages[1])

    def test_fail(self):
        from qc_tool.vector.inspire import run_check
        self.params["layer_defs"] = {"layer0": {"src_filepath": self.xml_dir.joinpath("inspire_bad.gdb")}}
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)
        self.assertIn("s01_inspire_bad_inspire_report.html", status.attachment_filenames)
        self.assertIn("s01_inspire_bad_inspire_log.txt", status.attachment_filenames)
