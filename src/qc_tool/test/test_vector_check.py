#!/usr/bin/env python3


from contextlib import closing

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
                            "campaign_years": ["2006", "2012"],
                            "filename_regex": "^clc(?P<reference_year>[0-9]{4})_(?P<country_code>.+).gdb$",
                            "reference_layer_regex": "^{country_code:s}/clc{reference_year_tail:s}_{country_code:s}$",
                            "initial_layer_regex": "^{country_code:s}/clc{initial_year_tail:s}_{country_code:s}$",
                            "change_layer_regex": "^{country_code:s}/cha{reference_year_tail:s}_{country_code:s}$",
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
        self.params["initial_layer_regex"] = "^{country_code:s}/xxx{initial_year_tail:s}_{country_code:s}$"
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
        self.params.update({"campaign_years": ["2006", "2012", "2018"],
                            "reference_layer_regex": "_ua(?P<reference_year>[0-9]{{4}})$",
                            "boundary_layer_regex": "^boundary{reference_year:s}_",
                            "revised_layer_regex": "_ua{revised_year:s}_revised$",
                            "combined_layer_regex": "_ua{revised_year:s}_{reference_year:s}$",
                            "change_layer_regex": "_change_{revised_year:s}_{reference_year:s}$"})

    def test(self):
        from qc_tool.wps.vector_check.v1_ua import run_check
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
        from qc_tool.wps.vector_check.v1_ua import run_check
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
        self.params.update({"campaign_years": ["2006", "2012", "2018"],
                            "reference_layer_regex": "_ua(?P<reference_year>[0-9]{{4}})$",
                            "boundary_layer_regex": "^boundary{reference_year:s}_"})

    def test(self):
        from qc_tool.wps.vector_check.v1_ua import run_check
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
                            "layers": ["layer_0", "layer_1"],
                            "attribute_regexes": ["id", "code_(06|12|18)", "area_ha", "remark"]})

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
        self.assertEqual(2, len(status.messages))


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
        from qc_tool.wps.vector_check.v1_ua import run_check as layer_check

        zip_filepath = TEST_DATA_DIR.joinpath("vector", "ua_shp", "EE003L0_NARVA.shp.zip")
        self.params.update({"tmp_dir": self.params["jobdir_manager"].tmp_dir,
                            "filepath": zip_filepath})
        status = self.status_class()
        unzip_check(self.params, status)
        self.params["unzip_dir"] = status.params["unzip_dir"]

        self.params.update({"campaign_years": ["2006", "2012", "2018"],
                            "reference_layer_regex": "_ua(?P<reference_year>[0-9]{{4}})$",
                            "boundary_layer_regex": "^boundary{reference_year:s}_"})
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
        self.assertEqual(1, len(status.attachment_filenames))


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
                            "code_regex": "^...(..)",
                            "code_to_column_defs": {"18": [["code_18", "CLC"]]}})
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
                            "code_regex": "^...(..)",
                            "code_to_column_defs": {"12": [["code_12", "INTEGER_CODES"]]}})
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
                            "code_regex": "^...(..)",
                            "code_to_column_defs": {"12": [["code_12", "INTEGER_CODES"]]}})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)
        self.assertEqual(1, len(status.attachment_filenames))

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
                            "code_regex": "^...(..)",
                            "code_to_column_defs": {"18": [["code_12", "CLC"], ["code_18", "CLC"]]}})
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
                            "code_regex": "^...(..)",
                            "code_to_column_defs": {"18": [["code_12", "CLC"], ["code_18", "CLC"]]}})
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
        self.assertEqual(1, len(status.attachment_filenames))

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
                            "area_ha": 25,
                            "border_exception": True})
        status = self.status_class()
        import_check(self.params, status)
        self.params["layers"] = ["reference"]

    def test_small_mmu(self):
        from qc_tool.wps.vector_check.v11 import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status, "Check result should be ok for MMU=25ha.")

    def test_big_mmu_fails(self):
        from qc_tool.wps.vector_check.v11 import run_check
        self.params["area_ha"] = 250
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
                            "code_colnames": ["attr_1", "attr_2"]})

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
