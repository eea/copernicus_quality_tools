#!/usr/bin/env python3


from contextlib import closing

from qc_tool.common import TEST_DATA_DIR
from qc_tool.test.helper import VectorCheckTestCase


class TestV2_gdb(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.params.update({"filepath": TEST_DATA_DIR.joinpath("clc2012_mt.gdb"),
                            "country_codes": "(MT)",
                            "file_name_regex": "^clc[0-9]{4}_countrycode.gdb$",
                            "layer_prefix": "^{countrycode:s}/clc",
                            "layer_regex": "^{countrycode:s}/clc[0-9]{{2}}_{countrycode:s}$",
                            "layer_count": 2
                           })

    def test_v2_gdb_clc_ok(self):
        from qc_tool.wps.vector_check.v2_gdb import run_check
        result = run_check(self.params)
        self.assertEqual("ok", result["status"])
        self.assertIn("layer_names", result["params"])

    def test_v2_gdb_prefix_fail(self):
        self.params["layer_prefix"] = "^{countrycode:s}/cha"
        from qc_tool.wps.vector_check.v2_gdb import run_check
        result = run_check(self.params)
        self.assertEqual("aborted", result["status"])

    def test_v2_gdb_count_fail(self):
        self.params["layer_count"] = 1
        from qc_tool.wps.vector_check.v2_gdb import run_check
        result = run_check(self.params)
        self.assertEqual("aborted", result["status"])


class TestV3(VectorCheckTestCase):
    valid_geodatabase = "clc2012_mt.gdb"
    def setUp(self):
        super().setUp()
        self.params.update({"filepath": TEST_DATA_DIR.joinpath(self.valid_geodatabase),
                            "layer_names": ["clc12_mt"]})

    def test_v3_Malta_clc_ok(self):
        from qc_tool.wps.vector_check.v3 import run_check
        self.params["fields"] = ["^ID$", "^CODE_[0-9]{2}$", "^AREA_HA$", "^REMARK$"]
        result = run_check(self.params)
        self.assertEqual("ok", result["status"])

    def test_v3_missing_fields(self):
        from qc_tool.wps.vector_check.v3 import run_check
        self.params["fields"] = ["^ID2$", "^CODE_[0-9]{2}$", "^AREA_HA$", "^REMARK$", "^EXTRA_FIELD$"]
        result = run_check(self.params)
        self.assertEqual("failed", result["status"])


class TestVImport2pg(VectorCheckTestCase):
    valid_geodatabase = "clc2012_mt.gdb"
    def setUp(self):
        super().setUp()
        self.params.update({"filepath": TEST_DATA_DIR.joinpath(self.valid_geodatabase),
                            "layer_names": ["clc12_mt"]})

    def test_v_import2pg_pass(self):
        from qc_tool.wps.vector_check.v_import2pg import run_check
        result = run_check(self.params)
        self.assertEqual("ok", result["status"])

    def test_v_import2pg_bad_file_aborted(self):
        from qc_tool.wps.vector_check.v_import2pg import run_check
        self.params["filepath"] = TEST_DATA_DIR.joinpath("test_raster1.tif")
        result = run_check(self.params)
        self.assertEqual("aborted", result["status"], "Status was not 'aborted' when importing a file with bad format.")

    def test_v_import2pg_table_created(self):
        from qc_tool.wps.vector_check.v_import2pg import run_check
        run_check(self.params)

        cur = self.params["connection_manager"].get_connection().cursor()
        cur.execute("""SELECT id FROM {:s};""".format(self.params["layer_names"][0]))
        self.assertLess(0, cur.rowcount, "imported table should have at least one row.")

    def test_v_import2pg_functions_created(self):
        from qc_tool.wps.vector_check.v_import2pg import run_check
        run_check(self.params)

        job_schema = self.params["connection_manager"].get_dsn_schema()[1]
        expected_function_names = ["__v11_mmu_status",
                                   "__v11_mmu_polyline_border",
                                   "__v5_uniqueid",
                                   "__v6_validcodes",
                                   "__v8_multipartpolyg",
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
                            "layer_names": ["clc12_mt"],
                            "ident_colname": "id"})
        import_check(self.params)

    def test(self):
        from qc_tool.wps.vector_check.v5 import run_check
        result = run_check(self.params)
        self.assertEqual("ok", result["status"])


class TestV8(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        from qc_tool.wps.vector_check.v_import2pg import run_check as import_check
        self.params.update({"filepath": TEST_DATA_DIR.joinpath("clc2012_mt.gdb"),
                            "layer_names": ["clc12_mt"]})
        import_check(self.params)

    def test_v8_Malta(self):
        from qc_tool.wps.vector_check.v8 import run_check
        result = run_check(self.params)
        self.assertEqual("ok", result["status"], "Check result should be ok for Malta.")


class TestV11(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        from qc_tool.wps.vector_check.v_import2pg import run_check as import_check
        self.params.update({"filepath": TEST_DATA_DIR.joinpath("clc2012_mt.gdb"),
                            "layer_names": ["clc12_mt"],
                            "ident_colname": "id",
                            "area_ha": 25,
                            "border_exception": True})
        import_check(self.params)

    def test_v11_small_mmu_should_pass(self):
        from qc_tool.wps.vector_check.v11 import run_check
        result = run_check(self.params)
        self.assertEqual("ok", result["status"], "Check result should be ok for MMU=25ha.")

    def test_v11_big_mmu_should_fail(self):
        from qc_tool.wps.vector_check.v11 import run_check
        self.params["area_ha"] = 250
        result = run_check(self.params)
        self.assertEqual("failed", result["status"], "Check result should be 'failed' for MMU=250ha.")

    def test_v11_border_table(self):
        """
        a _polyline_border table should be created in the job's schema
        :return:
        """
        from qc_tool.wps.vector_check.v11 import run_check
        run_check(self.params)

        table_name = "{:s}_polyline_border".format(self.params["layer_names"][0])
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
        self.params.update({"layer_names": ["test_layer_1", "test_layer_2"],
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
        result = run_check(self.params)
        self.assertEqual("ok", result["status"])

    def test_overlapping(self):
        from qc_tool.wps.vector_check.v13 import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("INSERT INTO test_layer_1 VALUES (1, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                      " (5, ST_MakeEnvelope(0.9, 0, 2, 1, 4326));")
        cursor.execute("INSERT INTO test_layer_2 VALUES (1, ST_MakeEnvelope(0, 0, 1, 1, 4326)),"
                                                      " (5, ST_MakeEnvelope(0.9, 0, 2, 1, 4326)),"
                                                      " (6, ST_MakeEnvelope(0.8, 0, 3, 1, 4326));")
        result = run_check(self.params)
        self.assertEqual("failed", result["status"])
        self.assertEqual(["Layers with overlapping pairs: test_layer_1:1, test_layer_2:3."], result["messages"])
