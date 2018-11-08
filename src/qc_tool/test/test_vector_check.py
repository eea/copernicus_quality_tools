#!/usr/bin/env python3


from qc_tool.common import TEST_DATA_DIR
from qc_tool.test.helper import VectorCheckTestCase


class TestUnzip(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.params["tmp_dir"] = self.params["jobdir_manager"].tmp_dir

    def test_shp(self):
        from qc_tool.wps.vector_check.v_unzip import run_check
        self.params["filepath"] = TEST_DATA_DIR.joinpath("vector", "ua_shp", "EE003L0_NARVA.shp.zip")
        status = self.status_class()
        run_check(self.params, status)

        self.assertIn("unzip_dir", status.params)
        self.assertEqual("ok", status.status)

        unzip_dir = status.params["unzip_dir"]
        unzipped_subdir_names = [path.name for path in unzip_dir.glob("**")]
        unzipped_file_names = [path.name for path in unzip_dir.glob("**/*") if path.is_file()]

        self.assertIn("Shapefiles", unzipped_subdir_names,
                      "Unzipped directory should contain a 'Shapefiles' subdirectory.")
        self.assertIn("EE003L0_NARVA_UA2012.shp", unzipped_file_names,
                      "Unzipped directory should contain a file EE003L0_NARVA_UA2012.shp.")

    def test_gdb(self):
        from qc_tool.wps.vector_check.v_unzip import run_check
        self.params["filepath"] = TEST_DATA_DIR.joinpath("vector", "ua_gdb", "DK001L2_KOBENHAVN_clip.zip")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.assertIn("unzip_dir", status.params)
        unzip_dir = status.params["unzip_dir"]
        unzipped_subdir_names = [path.name for path in unzip_dir.glob("**") if path.is_dir()]
        self.assertIn("DK001L2_KOBENHAVN_clip.gdb", unzipped_subdir_names)

    def test_invalid_file(self):
        from qc_tool.wps.vector_check.v_unzip import run_check
        self.params["filepath"] = TEST_DATA_DIR.joinpath("non_existent_zip_file.zip")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status, "Unzipping a non-existent v_unzip should be aborted.")


class TestV1_rpz(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        from qc_tool.wps.vector_check.v_unzip import run_check as unzip_check
        self.params.update({"tmp_dir": self.params["jobdir_manager"].tmp_dir,
                            "filepath": TEST_DATA_DIR.joinpath("vector", "rpz", "RPZ_LCLU_DU026A.shp.zip")})
        status = self.status_class()
        unzip_check(self.params, status)
        self.params["unzip_dir"] = status.params["unzip_dir"]

    def test(self):
        from qc_tool.wps.vector_check.v1_rpz import run_check
        self.params.update({"filename_regex": "^rpz_{areacodes:s}[a-z]_lclu_v[0-9]{{2}}.shp$",
                            "areacodes": ["du026", "du027"]})
        status = self.status_class()
        run_check(self.params, status)

        self.assertEqual("ok", status.status)
        self.assertEqual(1, len(status.params["layer_defs"]))
        self.assertEqual("rpz_DU026A_lclu_v01.shp", status.params["layer_defs"]["rpz"]["src_filepath"].name)
        self.assertEqual("rpz_DU026A_lclu_v01", status.params["layer_defs"]["rpz"]["src_layer_name"])


class TestV1_clc(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.params.update({"unzip_dir": TEST_DATA_DIR.joinpath("vector", "clc"),
                            "country_codes": ["cz", "sk", "mt"],
                            "reference_year": "2012",
                            "filename_regex": "^clc2012_(?P<country_code>.+).gdb$",
                            "reference_layer_regex": "^{country_code:s}/clc12_{country_code:s}$",
                            "initial_layer_regex": "^{country_code:s}/clc06_{country_code:s}$",
                            "change_layer_regex": "^{country_code:s}/cha12_{country_code:s}$",
                            "boundary_dir": TEST_DATA_DIR.joinpath("boundary")})

    def test(self):
        from qc_tool.wps.vector_check.v1_clc import run_check
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
        self.assertEqual("boundary_mt.shp", status.params["layer_defs"]["boundary"]["src_filepath"].name)
        self.assertEqual("boundary_mt", status.params["layer_defs"]["boundary"]["src_layer_name"])

    def test_mismatched_regex_aborts(self):
        from qc_tool.wps.vector_check.v1_clc import run_check
        self.params["initial_layer_regex"] = "^{country_code:s}/xxx_{country_code:s}$"
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status)


class TestV1_ua_gdb(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        from qc_tool.wps.vector_check.v_unzip import run_check as unzip_check
        self.params.update({"tmp_dir": self.params["jobdir_manager"].tmp_dir,
                            "filepath": TEST_DATA_DIR.joinpath("vector", "ua_gdb", "DK001L2_KOBENHAVN_clip.zip")})
        status = self.status_class()
        unzip_check(self.params, status)
        self.params["unzip_dir"] = status.params["unzip_dir"]
        self.params.update({"reference_year": "2012",
                            "reference_layer_regex": "_ua2012$",
                            "boundary_layer_regex": "^boundary2012_",
                            "revised_layer_regex": "_ua2006_revised$",
                            "combined_layer_regex": "_ua2006_2012$",
                            "change_layer_regex": "_change_2006_2012$"})

    def test(self):
        from qc_tool.wps.vector_check.v1_ua_gdb import run_check
        status = self.status_class()
        run_check(self.params, status)

        self.assertEqual("ok", status.status)
        self.assertEqual(5, len(status.params["layer_defs"]))
        self.assertEqual("DK001L2_KOBENHAVN_clip.gdb", status.params["layer_defs"]["reference"]["src_filepath"].name)
        self.assertEqual("DK001L2_KOBENHAVN_UA2012", status.params["layer_defs"]["reference"]["src_layer_name"])
        self.assertEqual("DK001L2_KOBENHAVN_clip.gdb", status.params["layer_defs"]["boundary"]["src_filepath"].name)
        self.assertEqual("Boundary2012_DK001L2_KOBENHAVN", status.params["layer_defs"]["boundary"]["src_layer_name"])
        self.assertEqual("DK001L2_KOBENHAVN_clip.gdb", status.params["layer_defs"]["revised"]["src_filepath"].name)
        self.assertEqual("DK001L2_KOBENHAVN_UA2006_Revised", status.params["layer_defs"]["revised"]["src_layer_name"])
        self.assertEqual("DK001L2_KOBENHAVN_clip.gdb", status.params["layer_defs"]["combined"]["src_filepath"].name)
        self.assertEqual("DK001L2_KOBENHAVN_UA2006_2012", status.params["layer_defs"]["combined"]["src_layer_name"])
        self.assertEqual("DK001L2_KOBENHAVN_clip.gdb", status.params["layer_defs"]["change"]["src_filepath"].name)
        self.assertEqual("DK001L2_KOBENHAVN_Change_2006_2012", status.params["layer_defs"]["change"]["src_layer_name"])

    def test_non_existing_aborts(self):
        from qc_tool.wps.vector_check.v1_ua_gdb import run_check
        self.params["boundary_layer_regex"] = "non-existing-layer-name"
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status)


class TestV1_ua_shp(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        from qc_tool.wps.vector_check.v_unzip import run_check as unzip_check
        self.params.update({"tmp_dir": self.params["jobdir_manager"].tmp_dir,
                            "filepath": TEST_DATA_DIR.joinpath("vector", "ua_shp", "EE003L0_NARVA.shp.zip")})
        status = self.status_class()
        unzip_check(self.params, status)
        self.params["unzip_dir"] = status.params["unzip_dir"]
        self.params.update({"reference_year": "2012",
                            "reference_layer_regex": "_ua2012$",
                            "boundary_layer_regex": "^boundary2012_"})

    def test(self):
        from qc_tool.wps.vector_check.v1_ua_shp import run_check
        status = self.status_class()
        run_check(self.params, status)

        self.assertEqual("ok", status.status)
        self.assertEqual(2, len(status.params["layer_defs"]))
        self.assertEqual("EE003L0_NARVA_UA2012.shp", status.params["layer_defs"]["reference"]["src_filepath"].name)
        self.assertEqual("EE003L0_NARVA_UA2012", status.params["layer_defs"]["reference"]["src_layer_name"])
        self.assertEqual("Boundary2012_EE003L0_NARVA.shp", status.params["layer_defs"]["boundary"]["src_filepath"].name)
        self.assertEqual("Boundary2012_EE003L0_NARVA", status.params["layer_defs"]["boundary"]["src_layer_name"])


class TestV2(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        from qc_tool.wps.vector_check.v_unzip import run_check as unzip_check
        from qc_tool.wps.vector_check.v1_rpz import run_check as layer_check

        rpz_filepath = TEST_DATA_DIR.joinpath("vector", "rpz", "RPZ_LCLU_DU026A.shp.zip")
        self.params.update({"tmp_dir": self.params["jobdir_manager"].tmp_dir,
                            "filepath": rpz_filepath,
                            "formats": [".gdb", ".shp"],
                            "drivers": {".shp": "ESRI Shapefile",".gdb": "OpenFileGDB"},
                            "filename_regex": "^rpz_{areacodes:s}[a-z]_lclu_v[0-9]{{2}}.shp$",
                            "areacodes": ["du026", "du027"]})

        status = self.status_class()
        unzip_check(self.params, status)
        self.params["unzip_dir"] = status.params["unzip_dir"]

        status = self.status_class()
        layer_check(self.params, status)
        self.params["layer_defs"] = status.params["layer_defs"]
        self.params["layers"] = ["rpz"]

    def test(self):
        from qc_tool.wps.vector_check.v2 import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_incorrect_format_aborts(self):
        from qc_tool.wps.vector_check.v2 import run_check
        status = self.status_class()
        self.params["formats"] = [".gdb"]
        run_check(self.params, status)
        self.assertEqual("aborted", status.status)


class TestV3(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        gdb_dir = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb")
        self.params.update({"layer_defs": {"layer_0": {"src_filepath": gdb_dir,
                                                       "src_layer_name": "clc06_mt"},
                                           "layer_1": {"src_filepath": gdb_dir,
                                                       "src_layer_name": "clc12_mt"}},
                            "layers": ["layer_0"],
                            "attribute_regexes": ["id", "code_06", "area_ha", "remark"]})

    def test(self):
        from qc_tool.wps.vector_check.v3 import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_missing_attribute_aborts(self):
        from qc_tool.wps.vector_check.v3 import run_check
        self.params["attribute_regexes"] = ["missing_attribute"]
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status)
        self.assertEqual(1, len(status.messages))


class TestV4_gdb(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        gdb_dir = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb")
        self.params.update({"layer_defs": {"layer_0": {"src_filepath": gdb_dir,
                                                       "src_layer_name": "clc06_mt"},
                                           "layer_1": {"src_filepath": gdb_dir,
                                                       "src_layer_name": "clc12_mt"}},
                            "layers": ["layer_0", "layer_1"],
                            "epsg": [23033]})

    def test(self):
        from qc_tool.wps.vector_check.v4 import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.assertEqual(23033, status.params["layer_srs_epsg"])

    def test_mismatched_epsg_aborts(self):
        from qc_tool.wps.vector_check.v4 import run_check
        self.params["epsg"] = [7777]
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status)
        self.assertNotIn("layer_srs_epsg", status.params)


class TestV4_shp(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        from qc_tool.wps.vector_check.v_unzip import run_check as unzip_check
        from qc_tool.wps.vector_check.v1_ua_shp import run_check as layer_check

        zip_filepath = TEST_DATA_DIR.joinpath("vector", "ua_shp", "EE003L0_NARVA.shp.zip")
        self.params.update({"tmp_dir": self.params["jobdir_manager"].tmp_dir,
                            "filepath": zip_filepath})
        status = self.status_class()
        unzip_check(self.params, status)
        self.params["unzip_dir"] = status.params["unzip_dir"]

        self.params.update({"reference_year": "2012",
                            "reference_layer_regex": "_ua2012$",
                            "boundary_layer_regex": "^boundary2012_"})
        status = self.status_class()
        layer_check(self.params, status)
        self.params["layer_defs"] = status.params["layer_defs"]
        self.params.update({"layers": ["reference", "boundary"],
                            "epsg": [3035]})

    def test(self):
        from qc_tool.wps.vector_check.v4 import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.assertIn("layer_srs_epsg", status.params)
        self.assertEqual(3035, status.params["layer_srs_epsg"])


class TestVImport2pg(VectorCheckTestCase):
    def setUp(self):
        super().setUp()

    def test(self):
        from qc_tool.wps.vector_check.v_import2pg import run_check
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
        from qc_tool.wps.vector_check.v_import2pg import run_check
        bad_filepath = TEST_DATA_DIR.joinpath("raster", "checks", "r11", "test_raster1.tif")
        self.params.update({"layer_defs": {"layer_0": {"src_filepath": bad_filepath,
                                                       "src_layer_name": "irrelevant_layer"}},
                            "layers": ["layer_0"]})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status)

    def test_precision(self):
        """ogr2ogr parameter PRECISION=NO should supress numeric field overflow error."""
        from qc_tool.wps.vector_check.v_import2pg import run_check
        shp_filepath = TEST_DATA_DIR.joinpath("vector", "ua_shp", "ES031L1_LUGO_boundary", "ES031L1_LUGO_UA2012_Boundary.shp")
        self.params.update({"layer_defs": {"layer_0": {"src_filepath": shp_filepath,
                                                       "src_layer_name": "ES031L1_LUGO_UA2012_Boundary"}},
                            "layers": ["layer_0"]})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)


class TestV5(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.params.update({"output_dir": self.params["jobdir_manager"].output_dir})

    def test(self):
        from qc_tool.wps.vector_check.v5 import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE mytable (fid integer, "
                       "unique_1 varchar, unique_2 integer, wkb_geometry geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO mytable (fid, unique_1, unique_2, wkb_geometry) VALUES "
                       " (1, 'a', 33, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                       " (2, 'b', 34, ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                       " (3, 'c', 35, ST_MakeEnvelope(3, 1, 4, 2, 4326));")
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "mytable",
                                                       "pg_fid_name": "fid"}},
                            "layers": ["layer_0"],
                            "unique_keys": ["unique_1", "unique_2"]})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_fail(self):
        from qc_tool.wps.vector_check.v5 import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE mytable (fid integer, "
                       "ident varchar, wkb_geometry geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO mytable (fid, ident, wkb_geometry) VALUES "
                       " (1, 'a', ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                       " (2, 'b', ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                       " (3, 'b', ST_MakeEnvelope(3, 1, 4, 2, 4326));")
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "mytable",
                                                       "pg_fid_name": "fid"}},
                            "layers": ["layer_0"],
                            "unique_keys": ["ident"]})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)
        self.assertEqual(1, len(status.messages))


class TestV6(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.params.update({"output_dir": self.params["jobdir_manager"].output_dir})
        self.params.update({"codes": {"CLC":['111','112'], "INTEGER_CODES":[1, 2, 3, 4]}})

    def test_string_codes(self):
        from qc_tool.wps.vector_check.v6 import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE xxx18_zz (fid integer, "
                       "code_18 varchar, wkb_geometry geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO xxx18_zz VALUES (1, '112', ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                  " (2, '111', ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                                                  " (3, '111', ST_MakeEnvelope(3, 1, 4, 2, 4326));")
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "xxx18_zz",
                                                       "pg_fid_name": "fid"}},
                            "layers": ["layer_0"],
                            "column_defs": [["code_18", "CLC"]]})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_integer_codes(self):
        from qc_tool.wps.vector_check.v6 import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE xxx12_zz (fid integer, "
                       "code_12 integer, wkb_geometry geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO xxx12_zz VALUES (1, 2, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                       " (2, 3, ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                       " (3, 4, ST_MakeEnvelope(3, 1, 4, 2, 4326));")
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "xxx12_zz",
                                                       "pg_fid_name": "fid"}},
                            "layers": ["layer_0"],
                            "column_defs": [["code_12", "INTEGER_CODES"]]})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_integer_codes_fail(self):
        from qc_tool.wps.vector_check.v6 import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE xxx12_zz (fid integer, "
                       "code_12 integer, wkb_geometry geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO xxx12_zz VALUES (1, 2, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                       " (2, 9999, ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                       " (3, 9999, ST_MakeEnvelope(3, 1, 4, 2, 4326));")
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "xxx12_zz",
                                                       "pg_fid_name": "fid"}},
                            "layers": ["layer_0"],
                            "column_defs": [["code_12", "INTEGER_CODES"]]})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)

    def test_change_fail(self):
        from qc_tool.wps.vector_check.v6 import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE cha18_xx (fid integer, code_12 varchar, "
                       "code_18 varchar, wkb_geometry geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO cha18_xx VALUES (1, '111', '112', ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                  " (2, 'xxx', 'xxx', ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                                                  " (3, 'xxx', '111', ST_MakeEnvelope(3, 1, 4, 2, 4326));")
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "cha18_xx",
                                                       "pg_fid_name": "fid"}},
                            "layers": ["layer_0"],
                            "column_defs": [["code_12", "CLC"], ["code_18", "CLC"]]})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)
        self.assertEqual(2, len(status.messages))

    def test_null(self):
        """v6 should fail if code column has NULL values."""
        from qc_tool.wps.vector_check.v6 import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE cha18_xx (fid integer, code_12 varchar, "
                       "code_18 varchar, wkb_geometry geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO cha18_xx VALUES (1, '111', NULL, ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "cha18_xx",
                                                       "pg_fid_name": "fid"}},
                            "layers": ["layer_0"],
                            "column_defs": [["code_12", "CLC"], ["code_18", "CLC"]]})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)
        self.assertEqual(1, len(status.messages))


class TestV8(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.params.update({"output_dir": self.params["jobdir_manager"].output_dir})

    def test(self):
        from qc_tool.wps.vector_check.v8 import run_check
        status = self.status_class()
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE mytable (fid integer, "
                       "wkb_geometry geometry(Multipolygon, 4326));")
        cursor.execute("INSERT INTO mytable "
                       "VALUES (1, ST_Multi(ST_MakeEnvelope(0, 0, 1, 1, 4326))),"
                       "       (3, ST_Multi(ST_MakeEnvelope(3, 3, 4, 4, 4326)));")
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "mytable",
                                                       "pg_fid_name": "fid"}},
                            "layers": ["layer_0"]})
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_fail(self):
        from qc_tool.wps.vector_check.v8 import run_check
        status = self.status_class()
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE mytable (fid integer, wkb_geometry geometry(Multipolygon, 4326));")
        cursor.execute("INSERT INTO mytable "
                       "VALUES (1, ST_Union(ST_MakeEnvelope(0, 0, 1, 1, 4326), "
                       "                    ST_MakeEnvelope(3, 3, 4, 4, 4326)));")
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "mytable", "pg_fid_name": "fid"}},
                            "layers": ["layer_0"]})
        run_check(self.params, status)
        self.assertEqual("failed", status.status)


class Test_v11_clc_status(VectorCheckTestCase):
    def test(self):
        from qc_tool.wps.vector_check.v11_clc_status import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE boundary (wkb_geometry geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO boundary VALUES (ST_MakeEnvelope(0, 0, 100, 100, 4326));")
        cursor.execute("CREATE TABLE layer (fid integer, shape_area real, wkb_geometry geometry(Polygon, 4326));")

        # General features.
        cursor.execute("INSERT INTO layer VALUES (10, 250001, ST_MakeEnvelope(10, 1, 11, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (12, 250000, ST_MakeEnvelope(12, 0, 13, 2, 4326));")
        # Exception feature touching boundary.
        cursor.execute("INSERT INTO layer VALUES (20, 249999, ST_MakeEnvelope(20, 0, 21, 2, 4326));")
        # Error feature.
        cursor.execute("INSERT INTO layer VALUES (30, 249999, ST_MakeEnvelope(30, 1, 31, 2, 4326));")

        self.params.update({"layer_defs": {"boundary": {"pg_layer_name": "boundary",
                                                        "pg_fid_name": "fid"},
                                           "layer": {"pg_layer_name": "layer",
                                                     "pg_fid_name": "fid"}},
                            "layers": ["layer"],
                            "area_column_name": "shape_area",
                            "area_m2": 250000})
        run_check(self.params, self.status_class())
        cursor.execute("SELECT fid FROM v11_layer_general;")
        self.assertListEqual([(10,), (12,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM v11_layer_exception;")
        self.assertListEqual([(20,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM v11_layer_error;")
        self.assertListEqual([(30,)], cursor.fetchall())


class Test_v11_clc_change(VectorCheckTestCase):
    def test(self):
        from qc_tool.wps.vector_check.v11_clc_change import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE boundary (wkb_geometry geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO boundary VALUES (ST_MakeEnvelope(0, 0, 100, 100, 4326));")
        cursor.execute("CREATE TABLE layer (fid integer, shape_area real, code1 char(1), code2 char(1), wkb_geometry geometry(Polygon, 4326));")

        # General features.
        cursor.execute("INSERT INTO layer VALUES (10, 50001, 'X', 'X', ST_MakeEnvelope(10, 1, 11, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (12, 50000, 'X', 'X', ST_MakeEnvelope(12, 1, 13, 2, 4326));")
        # General features touching boundary.
        cursor.execute("INSERT INTO layer VALUES (14, 50001, 'X', 'X', ST_MakeEnvelope(14, 0, 15, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (16, 50000, 'X', 'X', ST_MakeEnvelope(16, 0, 17, 2, 4326));")
        # Exception feature touching boundary.
        cursor.execute("INSERT INTO layer VALUES (20, 49999, 'X', 'X', ST_MakeEnvelope(20, 0, 21, 2, 4326));")
        # Exception pair of features taking part in complex change with the same code in initial year.
        cursor.execute("INSERT INTO layer VALUES (22, 40000, 'X', '1', ST_MakeEnvelope(22, 1, 23, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (23, 10000, 'X', '2', ST_MakeEnvelope(23, 1, 24, 2, 4326));")
        # Exception pair of features taking part in complex change with the same code in final year.
        cursor.execute("INSERT INTO layer VALUES (25, 40000, '1', 'X', ST_MakeEnvelope(25, 1, 26, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (26, 10000, '2', 'X', ST_MakeEnvelope(26, 1, 27, 2, 4326));")
        # Error feature.
        cursor.execute("INSERT INTO layer VALUES (30, 49999, 'X', 'X', ST_MakeEnvelope(30, 1, 31, 2, 4326));")
        # Error feature, complex change with total area below limit.
        cursor.execute("INSERT INTO layer VALUES (32, 40000, '1', 'X', ST_MakeEnvelope(32, 1, 33, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (33,  9999, '2', 'X', ST_MakeEnvelope(33, 1, 34, 2, 4326));")

        self.params.update({"layer_defs": {"boundary": {"pg_layer_name": "boundary",
                                                        "pg_fid_name": "fid"},
                                           "layer": {"pg_layer_name": "layer",
                                                     "pg_fid_name": "fid"}},
                            "layers": ["layer"],
                            "area_column_name": "shape_area",
                            "area_m2": 50000,
                            "initial_code_column_name": "code1",
                            "final_code_column_name": "code2"})
        run_check(self.params, self.status_class())
        cursor.execute("SELECT * FROM v11_layer_general;")
        self.assertListEqual([(10,), (12,), (14,), (16,)], cursor.fetchall())
        cursor.execute("SELECT * FROM v11_layer_exception;")
        self.assertListEqual([(20,), (22,), (23,), (25,), (26,)], cursor.fetchall())
        cursor.execute("SELECT * FROM v11_layer_error;")
        self.assertListEqual([(30,), (32,), (33,)], cursor.fetchall())


class Test_v11_ua_status(VectorCheckTestCase):
    def test(self):
        from qc_tool.wps.vector_check.v11_ua_status import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE boundary (wkb_geometry geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO boundary VALUES (ST_MakeEnvelope(0, 0, 100, 100, 4326));")
        cursor.execute("CREATE TABLE layer (fid integer, shape_area real, code char(5), wkb_geometry geometry(Polygon, 4326));")

        # General features.
        cursor.execute("INSERT INTO layer VALUES (10, 1, '122', ST_MakeEnvelope(10, 1, 11, 8, 4326));")
        cursor.execute("INSERT INTO layer VALUES (12, 1, '1228', ST_MakeEnvelope(12, 1, 13, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (14, 1, '12288', ST_MakeEnvelope(14, 1, 15, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (16, 1, '1228', ST_MakeEnvelope(16, 1, 17, 2, 4326));")

        cursor.execute("INSERT INTO layer VALUES (18, 2501, '1', ST_MakeEnvelope(18, 1, 19, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (20, 2500, '1', ST_MakeEnvelope(20, 1, 21, 2, 4326));")

        cursor.execute("INSERT INTO layer VALUES (22, 10000, '2', ST_MakeEnvelope(22, 1, 23, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (24, 10000, '3', ST_MakeEnvelope(24, 1, 25, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (26, 10000, '4', ST_MakeEnvelope(26, 1, 27, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (28, 10000, '5', ST_MakeEnvelope(28, 1, 29, 2, 4326));")

        cursor.execute("INSERT INTO layer VALUES (30, 1, '9', ST_MakeEnvelope(30, 1, 31, 4, 4326));")

        # Exception features, touches fid=30.
        cursor.execute("INSERT INTO layer VALUES (40, 1, '2', ST_MakeEnvelope(31, 3, 41, 4, 4326));")

        # Exception feature, touches boundary.
        cursor.execute("INSERT INTO layer VALUES (42, 100, '2', ST_MakeEnvelope(42, 0, 43, 4, 4326));")

        # Warning feature, touches fid=10.
        cursor.execute("INSERT INTO layer VALUES (50, 500, '2', ST_MakeEnvelope(11, 5, 51, 6, 4326));")

        # Error features breaking general requirements.
        cursor.execute("INSERT INTO layer VALUES (60, 1, '123', ST_MakeEnvelope(60, 1, 61, 2, 4326));")

        cursor.execute("INSERT INTO layer VALUES (62, 2499, '1', ST_MakeEnvelope(63, 1, 63, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (64, 2499, '13', ST_MakeEnvelope(65, 1, 65, 2, 4326));")

        cursor.execute("INSERT INTO layer VALUES (66, 9999, '2', ST_MakeEnvelope(67, 1, 67, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (68, 9999, '3', ST_MakeEnvelope(69, 1, 69, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (70, 9999, '4', ST_MakeEnvelope(71, 1, 71, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (72, 9999, '5', ST_MakeEnvelope(73, 1, 73, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (74, 20000, '6', ST_MakeEnvelope(75, 1, 75, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (76, 20000, '7', ST_MakeEnvelope(77, 1, 77, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (78, 20000, '8', ST_MakeEnvelope(79, 1, 79, 2, 4326));")

        # Error feature breaking exception requirements.
        cursor.execute("INSERT INTO layer VALUES (80, 99, '4', ST_MakeEnvelope(80, 0, 81, 2, 4326));")

        # Error feature breaking warning requirements, touches fid=10.
        cursor.execute("INSERT INTO layer VALUES (82, 499, '2', ST_MakeEnvelope(11, 7, 83, 8, 4326));")

        self.params.update({"layer_defs": {"boundary": {"pg_layer_name": "boundary",
                                                        "pg_fid_name": "fid"},
                                           "layer": {"pg_layer_name": "layer",
                                                     "pg_fid_name": "fid"}},
                            "layers": ["layer"],
                            "area_column_name": "shape_area",
                            "code_column_name": "code"})
        run_check(self.params, self.status_class())
        cursor.execute("SELECT fid FROM v11_layer_general;")
        self.assertListEqual([(10,), (12,), (14,), (16,), (18,), (20,), (22,), (24,), (26,), (28,), (30,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM v11_layer_exception;")
        self.assertListEqual([(40,), (42,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM v11_layer_warning;")
        self.assertListEqual([(50,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM v11_layer_error;")
        self.assertListEqual([(60,), (62,), (64,), (66,), (68,), (70,), (72,), (74,), (76,), (78,), (80,), (82,)], cursor.fetchall())


class Test_v11_ua_change(VectorCheckTestCase):
    def test(self):
        from qc_tool.wps.vector_check.v11_ua_change import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE boundary (wkb_geometry geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO boundary VALUES (ST_MakeEnvelope(0, 0, 100, 100, 4326));")
        cursor.execute("CREATE TABLE layer (fid integer, shape_area real, code1 char(5), code2 char(5), wkb_geometry geometry(Polygon, 4326));")

        # General features.
        cursor.execute("INSERT INTO layer VALUES (10, 1001, 'X', '1', ST_MakeEnvelope(10, 1, 11, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (12, 1000, 'X', '1', ST_MakeEnvelope(12, 1, 13, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (14, 1000, 'X', '12', ST_MakeEnvelope(14, 1, 15, 2, 4326));")

        cursor.execute("INSERT INTO layer VALUES (16, 2500, 'X', '2', ST_MakeEnvelope(16, 1, 17, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (18, 2500, 'X', '3', ST_MakeEnvelope(18, 1, 19, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (20, 2500, 'X', '4', ST_MakeEnvelope(20, 1, 21, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (22, 2500, 'X', '5', ST_MakeEnvelope(22, 1, 23, 2, 4326));")

        # Exception features.
        cursor.execute("INSERT INTO layer VALUES (30, 1, '122', 'X', ST_MakeEnvelope(30, 1, 31, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (32, 1, 'X', '122', ST_MakeEnvelope(32, 1, 33, 2, 4326));")

        # Error features breaking general requirements.
        cursor.execute("INSERT INTO layer VALUES (40, 999, 'X', '1', ST_MakeEnvelope(40, 1, 11, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (42, 999, 'X', '12', ST_MakeEnvelope(42, 1, 11, 2, 4326));")

        cursor.execute("INSERT INTO layer VALUES (44, 2499, 'X', '2', ST_MakeEnvelope(44, 1, 45, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (46, 2499, 'X', '3', ST_MakeEnvelope(46, 1, 46, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (48, 2499, 'X', '4', ST_MakeEnvelope(48, 1, 48, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (50, 2499, 'X', '5', ST_MakeEnvelope(50, 1, 50, 2, 4326));")

        cursor.execute("INSERT INTO layer VALUES (52, 20000, 'X', '6', ST_MakeEnvelope(52, 1, 53, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (54, 20000, 'X', '7', ST_MakeEnvelope(54, 1, 55, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (56, 20000, 'X', '8', ST_MakeEnvelope(56, 1, 57, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (58, 20000, 'X', '9', ST_MakeEnvelope(58, 1, 59, 2, 4326));")

        # Error features breaking exception requirements.
        cursor.execute("INSERT INTO layer VALUES (60, 1, '123', 'X', ST_MakeEnvelope(12, 1, 13, 2, 4326));")
        cursor.execute("INSERT INTO layer VALUES (62, 1, 'X', '123', ST_MakeEnvelope(12, 1, 13, 2, 4326));")

        self.params.update({"layer_defs": {"boundary": {"pg_layer_name": "boundary",
                                                        "pg_fid_name": "fid"},
                                           "layer": {"pg_layer_name": "layer",
                                                     "pg_fid_name": "fid"}},
                            "layers": ["layer"],
                            "area_column_name": "shape_area",
                            "initial_code_column_name": "code1",
                            "final_code_column_name": "code2"})
        run_check(self.params, self.status_class())
        cursor.execute("SELECT fid FROM v11_layer_general;")
        self.assertListEqual([(10,), (12,), (14,), (16,), (18,), (20,), (22,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM v11_layer_exception;")
        self.assertListEqual([(30,), (32,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM v11_layer_error;")
        self.assertListEqual([(40,), (42,), (44,), (46,), (48,), (50,), (52,), (54,), (56,), (58,), (60,), (62,)], cursor.fetchall())


class TestV11(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        from qc_tool.wps.vector_check.v_import2pg import run_check as import_check
        gdb_dir = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb")
        boundary_filepath = TEST_DATA_DIR.joinpath("boundary", "vector", "boundary_mt.shp")
        self.params.update({"layer_defs": {"reference": {"src_filepath": gdb_dir,
                                                         "src_layer_name": "clc12_mt"},
                                           "boundary": {"src_filepath": boundary_filepath,
                                                        "src_layer_name": "boundary_mt"}},
                            "layers": ["reference", "boundary"],
                            "area_m2": 250000,
                            "area_column_name": "shape_area"})
        status = self.status_class()
        import_check(self.params, status)
        self.params["layers"] = ["reference"]

    def test_small_mmu(self):
        from qc_tool.wps.vector_check.v11_clc_status import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status, "Check result should be ok for MMU=25ha.")

    def test_big_mmu_fails(self):
        from qc_tool.wps.vector_check.v11_clc_status import run_check
        self.params["area_m2"] = 2500000
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status, "Check result should be 'failed' for MMU=250ha.")


class TestV13(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE test_layer_1 (fid integer, wkb_geometry geometry(Polygon, 4326));")
        cursor.execute("CREATE TABLE test_layer_2 (fid integer, wkb_geometry geometry(Polygon, 4326));")
        self.params.update({"layer_defs": {"layer_1": {"pg_layer_name": "test_layer_1",
                                                       "pg_fid_name": "fid"},
                                           "layer_2": {"pg_layer_name": "test_layer_2",
                                                       "pg_fid_name": "fid"}},
                            "layers": ["layer_1", "layer_2"]})

    def test_non_overlapping(self):
        from qc_tool.wps.vector_check.v13 import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("INSERT INTO test_layer_1 VALUES (1, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                      " (2, ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                                                      " (3, ST_MakeEnvelope(3, 1, 4, 2, 4326)),"
                                                      " (4, ST_MakeEnvelope(4, 1, 5, 2, 4326));")
        cursor.execute("INSERT INTO test_layer_2 VALUES (1, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                      " (2, ST_MakeEnvelope(2, 0, 3, 1, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_overlapping_fails(self):
        from qc_tool.wps.vector_check.v13 import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("INSERT INTO test_layer_1 VALUES (1, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                      " (5, ST_MakeEnvelope(0.9, 0, 2, 1, 4326));")
        cursor.execute("INSERT INTO test_layer_2 VALUES (1, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                      " (5, ST_MakeEnvelope(0.9, 0, 2, 1, 4326)),"
                                                      " (6, ST_MakeEnvelope(0.8, 0, 3, 1, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)
        result = {"The layer test_layer_1 has overlapping pairs in rows: 1-5.",
                  "The layer test_layer_2 has overlapping pairs in rows: 1-5, 1-6, 5-6."}
        self.assertSetEqual(result, set(status.messages))


class TestV14(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        from qc_tool.wps.vector_check.v14 import run_check
        self.run_check = run_check
        self.cursor = self.params["connection_manager"].get_connection().cursor()
        self.cursor.execute("CREATE TABLE test_layer ("
                            "  fid integer,"
                            "  attr_1 char(1),"
                            "  attr_2 char(1),"
                            "  wkb_geometry geometry(Polygon, 4326));")
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "test_layer",
                                                       "pg_fid_name": "fid"}},
                            "layers": ["layer_0"],
                            "code_column_names": ["attr_1", "attr_2"]})

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
