#!/usr/bin/env python3


from contextlib import closing

from qc_tool.common import TEST_DATA_DIR
from qc_tool.test.helper import VectorCheckTestCase

class TestUnzip(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.params["tmp_dir"] = self.params["jobdir_manager"].tmp_dir

    def test_unzip_shp(self):
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

    def test_unzip_gdb(self):
        print("test_unzip_both_gdb")
        from qc_tool.wps.vector_check.v_unzip import run_check
        self.params["filepath"] = TEST_DATA_DIR.joinpath("vector", "ua_gdb", "SK007L1_TRNAVA.gdb.zip")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.assertIn("unzip_dir", status.params)
        unzip_dir = status.params["unzip_dir"]
        unzipped_subdir_names = [path.name for path in unzip_dir.glob("**") if path.is_dir()]
        self.assertIn("SK007L1_TRNAVA.gdb", unzipped_subdir_names)

    def test_unzip_invalid_file(self):
        from qc_tool.wps.vector_check.v_unzip import run_check
        self.params["filepath"] = TEST_DATA_DIR.joinpath("non_existent_zip_file.zip")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status, "Unzipping a non-existent v_unzip should be aborted.")


class TestV1_areacode(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        from qc_tool.wps.vector_check.v_unzip import run_check as unzip_check
        self.params.update({"tmp_dir": self.params["jobdir_manager"].tmp_dir,
                            "filepath": TEST_DATA_DIR.joinpath("vector", "rpz", "RPZ_LCLU_DU026A.shp.zip")})
        status = self.status_class()
        unzip_check(self.params, status)
        self.params["unzip_dir"] = status.params["unzip_dir"]

    def test(self):
        from qc_tool.wps.vector_check.v1_areacode import run_check
        status = self.status_class()
        self.params["file_name_regex"] = "rpz_AREACODE[a-z]{1}_lclu_v[0-9]{2}.shp$"
        self.params["areacodes"] = ["du026", "du027"]

        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.assertIn("layer_sources", status.params)
        self.assertEqual(1, len(status.params["layer_sources"]))
        # testing if layer name in layer sources is correct
        self.assertEqual("rpz_du026a_lclu_v01", status.params["layer_sources"][0][0], "layer name must match.")
        # testing if associated filepath in layers sources is correct
        self.assertEqual("rpz_DU026A_lclu_v01.shp", status.params["layer_sources"][0][1].name, "filename must match.")


class TestV1_gdb(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.params.update({
                            "unzip_dir": TEST_DATA_DIR.joinpath("vector", "clc"),
                            "filepath": TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb"),
                            "country_codes": "(MT)",
                            "file_name_regex": "^clc[0-9]{4}_countrycode.gdb$",
                            "layer_prefix": "^{countrycode:s}/clc",
                            "layer_regex": "^{countrycode:s}/clc[0-9]{{2}}_{countrycode:s}$",
                            "layer_count": 2
                           })

    def test_v1_gdb_clc_ok(self):
        from qc_tool.wps.vector_check.v1_gdb import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.assertIn("layer_sources", status.params)
        # There should be two status layers in clc2012_mt.gdb.
        self.assertEqual(2, len(status.params["layer_sources"]))
        self.assertEqual("clc2012_mt.gdb", status.params["layer_sources"][0][1].name)
        self.assertEqual("clc2012_mt.gdb", status.params["layer_sources"][1][1].name)
        layer_names = [layer_source[0] for layer_source in status.params["layer_sources"]]
        self.assertIn("clc12_mt", layer_names)
        self.assertIn("clc06_mt", layer_names)

    def test_v1_gdb_prefix_fail(self):
        self.params["layer_prefix"] = "^{countrycode:s}/cha"
        from qc_tool.wps.vector_check.v1_gdb import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status)

    def test_v1_gdb_count_fail(self):
        self.params["layer_count"] = 1
        from qc_tool.wps.vector_check.v1_gdb import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status)


class TestV2(VectorCheckTestCase):
    def setUp(self):
        super().setUp()

        # setup step 1: unzip
        from qc_tool.wps.vector_check.v_unzip import run_check as unzip_check
        rpz_filepath = TEST_DATA_DIR.joinpath("vector", "rpz", "RPZ_LCLU_DU026A.shp.zip")
        self.params.update({"filepath": rpz_filepath,
                            "tmp_dir": self.params["jobdir_manager"].tmp_dir
                           })
        status = self.status_class()
        unzip_check(self.params, status)
        self.params["unzip_dir"] = status.params["unzip_dir"]

        # setup step 2: get layer names
        from qc_tool.wps.vector_check.v1_areacode import run_check as layer_check
        status = self.status_class()
        self.params["file_name_regex"] = "rpz_AREACODE[a-z]{1}_lclu_v[0-9]{2}.shp$"
        self.params["areacodes"] = ["du026", "du027"]
        layer_check(self.params, status)
        self.params["layer_sources"] = status.params["layer_sources"]


    def test(self):
        from qc_tool.wps.vector_check.v2 import run_check
        status = self.status_class()
        self.params.update({"formats": [".gdb", ".shp"], "drivers": {".shp": "ESRI Shapefile",".gdb": "OpenFileGDB"}})
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_incorrect_format(self):
        from qc_tool.wps.vector_check.v2 import run_check
        status = self.status_class()
        self.params.update({"formats": [".gdb"], "drivers": {".shp": "ESRI Shapefile",".gdb": "OpenFileGDB"}})
        run_check(self.params, status)
        self.assertEqual("aborted", status.status, "Check v2 should be aborted if the file is not in expected format.")


class TestV3(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        gdb_path = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb")
        self.params.update({"filepath": TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb"),
                            "layer_sources": [["clc12_mt", gdb_path],["clc06_mt", gdb_path]]
                            })

    def test_v3_Malta_clc_ok(self):
        from qc_tool.wps.vector_check.v3 import run_check
        self.params["attribute_regexes"] = ["id", "code_(06|12|18)", "area_ha", "remark"]
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_v3_missing_fields(self):
        from qc_tool.wps.vector_check.v3 import run_check
        self.params["attribute_regexes"] = ["id", "code_(06|12|18)", "area_ha", "remark", "extra_field"]
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)
        self.assertEqual(2, len(status.messages))
        self.assertIn("has missing attributes: extra_field", status.messages[0])


class TestV4(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        gdb_path = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb")
        self.params.update({"filepath": TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb"),
                            "layer_sources": [["clc12_mt", gdb_path], ["clc06_mt", gdb_path]],
                            "epsg": [23033]
                            })

    def test(self):
        from qc_tool.wps.vector_check.v4 import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_fail(self):
        from qc_tool.wps.vector_check.v4 import run_check
        self.params["epsg"] = [7777]
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)


class TestVImport2pg(VectorCheckTestCase):
    gdb_filepath = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb")
    def setUp(self):
        super().setUp()
        self.params.update({"filepath": self.gdb_filepath,
                            "layer_sources": [["clc12_mt", self.gdb_filepath], ["clc06_mt", self.gdb_filepath]]})

    def test_v_import2pg_pass(self):
        from qc_tool.wps.vector_check.v_import2pg import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.assertIn("clc12_mt", status.params["db_layer_names"])
        self.assertIn("clc06_mt", status.params["db_layer_names"])

    def test_v_import2pg_bad_file_aborted(self):
        from qc_tool.wps.vector_check.v_import2pg import run_check
        self.params["layer_sources"] = [["bad_layer", TEST_DATA_DIR.joinpath("raster", "checks", "r11", "test_raster1.tif")]]
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status, "Status was not 'aborted' when importing a file with bad format.")

    def test_v_import2pg_table_created(self):
        from qc_tool.wps.vector_check.v_import2pg import run_check
        status = self.status_class()
        run_check(self.params, status)

        cur = self.params["connection_manager"].get_connection().cursor()
        cur.execute("""SELECT id FROM {:s};""".format(status.params["db_layer_names"][0]))
        self.assertLess(0, cur.rowcount, "imported table should have at least one row.")

    def test_v_import2pg_functions_created(self):
        from qc_tool.wps.vector_check.v_import2pg import run_check
        status = self.status_class()
        run_check(self.params, status)

        job_schema = self.params["connection_manager"].get_dsn_schema()[1]
        expected_function_names = ["__v11_mmu_status",
                                   "__v11_mmu_polyline_border",
                                   "__v11_mmu_change_clc"]
        conn = self.params["connection_manager"].get_connection()
        cur = conn.cursor()
        cur.execute("""SELECT routine_name FROM information_schema.routines \
                       WHERE routine_type='FUNCTION' AND routine_schema='{:s}'""".format(job_schema))

        actual_function_names = [row[0] for row in cur.fetchall()]

        for expected_name in expected_function_names:
            self.assertIn(expected_name, actual_function_names,
                          "a function {:s} should be created in schema {:s}".format(expected_name, job_schema))


class TestV5(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        from qc_tool.wps.vector_check.v_import2pg import run_check as import_check
        self.params.update({"product_code": "cha",
                            "filepath": TEST_DATA_DIR.joinpath("clc2012_mt.gdb"),
                            "layer_sources": [["clc12_mt", TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb")]],
                            "ident_colname": "id"})
        status = self.status_class()
        import_check(self.params, status)
        self.params["db_layer_names"] = status.params["db_layer_names"]

    def test(self):
        from qc_tool.wps.vector_check.v5 import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)


class TestV6(VectorCheckTestCase):
    def setUp(self):
        super().setUp()


    def test_status_pass(self):
        from qc_tool.wps.vector_check.v6 import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE xxx18_zz (id integer, code_18 varchar, wkb_geometry geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO xxx18_zz VALUES (1, '112', ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                  " (2, '111', ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                                                  " (3, '111', ST_MakeEnvelope(3, 1, 4, 2, 4326));")
        self.params["db_layer_names"] = ["xxx18_zz"]
        self.params["ident_colname"] = "id"
        self.params["code_regex"] = "^...(..)"
        self.params["code_to_column_def"] = {"18": [["code_18", "CLC"]]}
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_change_fail(self):
        from qc_tool.wps.vector_check.v6 import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE cha18_xx (id integer, code_12 varchar, code_18 varchar, wkb_geometry geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO cha18_xx VALUES (1, '111', '112', ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                  " (2, 'xxx', 'xxx', ST_MakeEnvelope(2, 0, 3, 1, 4326)),"
                                                  " (3, 'xxx', '111', ST_MakeEnvelope(3, 1, 4, 2, 4326));")

        self.params["db_layer_names"] = ["cha18_xx"]
        self.params["ident_colname"] = "id"
        self.params["code_regex"] = "^...(..)"
        self.params["code_to_column_def"] = {"18": [["code_12", "CLC"], ["code_18", "CLC"]]}
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)
        self.assertEqual(2, len(status.messages))

class TestV8(VectorCheckTestCase):
    def setUp(self):
        gdb_filepath = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb")
        super().setUp()
        from qc_tool.wps.vector_check.v_import2pg import run_check as import_check
        self.params.update({"filepath": TEST_DATA_DIR.joinpath("clc2012_mt.gdb"),
                            "layer_sources": [["clc12_mt", gdb_filepath]],
                            "ident_colname": "id"})
        status = self.status_class()
        import_check(self.params, status)
        self.params["db_layer_names"] = status.params["db_layer_names"]

    def test_v8_Malta(self):
        from qc_tool.wps.vector_check.v8 import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status, "Check result should be ok for Malta.")


class TestV11(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        gdb_filepath = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb")
        from qc_tool.wps.vector_check.v_import2pg import run_check as import_check
        self.params.update({"filepath": TEST_DATA_DIR.joinpath("clc2012_mt.gdb"),
                            "layer_sources": [["clc12_mt", gdb_filepath]],
                            "ident_colname": "id",
                            "area_ha": 25,
                            "border_exception": True})
        status = self.status_class()
        import_check(self.params, status)
        self.params["db_layer_names"] = status.params["db_layer_names"]

    def test_v11_small_mmu_should_pass(self):
        from qc_tool.wps.vector_check.v11 import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status, "Check result should be ok for MMU=25ha.")

    def test_v11_big_mmu_should_fail(self):
        from qc_tool.wps.vector_check.v11 import run_check
        self.params["area_ha"] = 250
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status, "Check result should be 'failed' for MMU=250ha.")

    def test_v11_border_table(self):
        """
        a _polyline_border table should be created in the job's schema
        :return:
        """
        from qc_tool.wps.vector_check.v11 import run_check
        status = self.status_class()
        run_check(self.params, status)

        table_name = "{:s}_polyline_border".format(self.params["db_layer_names"][0])
        dsn, job_schema_name =  self.params["connection_manager"].get_dsn_schema()
        cur = self.params["connection_manager"].get_connection().cursor()
        cur.execute("SELECT table_schema FROM information_schema.tables WHERE table_name=%s;", (table_name,))
        row = cur.fetchone()
        self.assertIsNotNone(row, "There should be polyline_border table created.")
        table_schema = row[0]
        self.assertNotEqual("public", table_schema, "polyline_border table should not be in public schema.")
        self.assertEqual(job_schema_name, table_schema, "polyline_border table is in {:s} schema instead of {:s} schema.".format(table_schema, job_schema_name))


class TestV13(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE test_layer_1 (ident integer, wkb_geometry geometry(Polygon, 4326));")
        cursor.execute("CREATE TABLE test_layer_2 (ident integer, wkb_geometry geometry(Polygon, 4326));")
        self.params.update({"db_layer_names": ["test_layer_1", "test_layer_2"],
                            "ident_colname": "ident"})

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

    def test_overlapping(self):
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
        result = ['Layer test_layer_1 has 1 overlapping pairs.', 'Layer test_layer_2 has 3 overlapping pairs.']
        self.assertEqual(result, status.messages)
