#!/usr/bin/env python3


from unittest import expectedFailure

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


class Test_v1_rpz(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        from qc_tool.wps.vector_check.v_unzip import run_check as unzip_check
        self.params.update({"tmp_dir": self.params["jobdir_manager"].tmp_dir,
                            "filepath": TEST_DATA_DIR.joinpath("vector", "rpz", "RPZ_LCLU_DU032B_clip2.zip"),
                            "boundary_dir": TEST_DATA_DIR.joinpath("boundaries")})
        status = self.status_class()
        unzip_check(self.params, status)
        self.params["unzip_dir"] = status.params["unzip_dir"]

    def test(self):
        from qc_tool.wps.vector_check.v1_rpz import run_check
        self.params.update({"filename_regex": "^rpz_du(?P<areacode>[0-9]{3})[a-z]_lclu_v[0-9]{2}.shp$",
                            "areacodes": ["026", "027", "032"]})
        status = self.status_class()
        run_check(self.params, status)

        self.assertEqual("ok", status.status)
        self.assertEqual("rpz_DU032B_lclu_v97.shp", status.params["layer_defs"]["rpz"]["src_filepath"].name)
        self.assertEqual("rpz_DU032B_lclu_v97", status.params["layer_defs"]["rpz"]["src_layer_name"])
        self.assertEqual("boundary_rpz.shp", status.params["layer_defs"]["boundary"]["src_filepath"].name)
        self.assertEqual("boundary_rpz", status.params["layer_defs"]["boundary"]["src_layer_name"])


class Test_v1_n2k(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        from qc_tool.wps.vector_check.v_unzip import run_check as unzip_check
        self.params.update({"tmp_dir": self.params["jobdir_manager"].tmp_dir,
                            "filepath": TEST_DATA_DIR.joinpath("vector", "n2k", "n2k_example_cz_correct.zip"),
                            "n2k_layer_regex": "^n2k_du[0-9]{3}[a-z]_lclu_v[0-9]+_[0-9]{8}$",
                            "boundary_dir": TEST_DATA_DIR.joinpath("boundaries")})
        status = self.status_class()
        unzip_check(self.params, status)
        self.params["unzip_dir"] = status.params["unzip_dir"]

    def test(self):
        from qc_tool.wps.vector_check.v1_n2k import run_check
        status = self.status_class()
        run_check(self.params, status)

        self.assertEqual("ok", status.status)
        self.assertEqual("n2k_du001z_lclu_v99_20190108.shp", status.params["layer_defs"]["n2k"]["src_filepath"].name)
        self.assertEqual("n2k_du001z_lclu_v99_20190108", status.params["layer_defs"]["n2k"]["src_layer_name"])
        self.assertEqual("boundary_n2k.shp", status.params["layer_defs"]["boundary"]["src_filepath"].name)
        self.assertEqual("boundary_n2k", status.params["layer_defs"]["boundary"]["src_layer_name"])

    def test_bad_layer_name_aborts(self):
        from qc_tool.wps.vector_check.v1_n2k import run_check

        # Rename layer to bad one.
        src_gdb_filepath = self.params["unzip_dir"].joinpath("n2k_du001z_lclu_v99_20170108", "n2k_du001z_lclu_v99_20190108.shp")
        dst_gdb_filepath = src_gdb_filepath.with_name("Xn2k_du001z_lclu_v99_20190108.shp")
        src_gdb_filepath.rename(dst_gdb_filepath)

        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status)


class Test_v1_clc(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.params.update({"unzip_dir": TEST_DATA_DIR.joinpath("vector", "clc"),
                            "country_codes": ["cz", "sk", "mt"],
                            "reference_year": "2012",
                            "gdb_filename_regex": "^clc2012_(?P<country_code>.+).gdb$",
                            "reference_layer_regex": "^{country_code:s}/clc12_{country_code:s}$",
                            "initial_layer_regex": "^{country_code:s}/clc06_{country_code:s}$",
                            "change_layer_regex": "^{country_code:s}/cha12_{country_code:s}$",
                            "boundary_dir": TEST_DATA_DIR.joinpath("boundaries")})

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
        self.assertEqual("boundary_clc_mt.shp", status.params["layer_defs"]["boundary"]["src_filepath"].name)
        self.assertEqual("boundary_clc_mt", status.params["layer_defs"]["boundary"]["src_layer_name"])

    def test_mismatched_regex_aborts(self):
        from qc_tool.wps.vector_check.v1_clc import run_check
        self.params["initial_layer_regex"] = "^{country_code:s}/xxx_{country_code:s}$"
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status)


class Test_v1_ua_gdb(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        from qc_tool.wps.vector_check.v_unzip import run_check as unzip_check
        self.params.update({"tmp_dir": self.params["jobdir_manager"].tmp_dir,
                            "filepath": TEST_DATA_DIR.joinpath("vector", "ua_gdb", "DK001L2_KOBENHAVN_clip.zip")})
        status = self.status_class()
        unzip_check(self.params, status)
        self.params["unzip_dir"] = status.params["unzip_dir"]
        self.params.update({"reference_year": "2012",
                            "gdb_filename_regex": "^[a-z0-9]{7}_.*$",
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

    def test_bad_gdb_filename_aborts(self):
        from qc_tool.wps.vector_check.v1_ua_gdb import run_check

        # Rename gdb filename to bad one.
        src_gdb_filepath = self.params["unzip_dir"].joinpath("DK001L2_KOBENHAVN_clip.gdb")
        dst_gdb_filepath = src_gdb_filepath.with_name("XDK001L2_KOBENHAVN_clip.gdb")
        src_gdb_filepath.rename(dst_gdb_filepath)

        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status)

    def test_missing_layer_aborts(self):
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

        rpz_filepath = TEST_DATA_DIR.joinpath("vector", "rpz", "RPZ_LCLU_DU032B_clip2.zip")
        self.params.update({"boundary_dir": TEST_DATA_DIR.joinpath("boundaries"),
                            "tmp_dir": self.params["jobdir_manager"].tmp_dir,
                            "filepath": rpz_filepath,
                            "formats": [".gdb", ".shp"],
                            "drivers": {".shp": "ESRI Shapefile",".gdb": "OpenFileGDB"},
                            "filename_regex": "^rpz_du(?P<areacode>[0-9]{3})[a-z]_lclu_v[0-9]{2}.shp$",
                            "areacodes": ["032"]})

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
                                                       "src_layer_name": "clc12_mt"}},
                            "layers": ["layer_0"],
                            "attributes": {"id": "string",
                                           "code_12": "string",
                                           "area_ha": "real",
                                           "remark": "string",
                                           "shape_length": "real",
                                           "shape_area": "real"}})

    def test(self):
        from qc_tool.wps.vector_check.v3 import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_missing_attribute_aborts(self):
        from qc_tool.wps.vector_check.v3 import run_check
        self.params["attributes"]["missing_attribute"] = "string"
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status)


class Test_v4_clc(VectorCheckTestCase):
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
        from qc_tool.wps.vector_check.v4_clc import run_check
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_missing_boundary_cancelled(self):
        from qc_tool.wps.vector_check.v4_clc import run_check
        del self.params["layer_defs"]["boundary"]
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("cancelled", status.status)


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

    def test_mismatched_epsg_aborts(self):
        from qc_tool.wps.vector_check.v4 import run_check
        self.params["epsg"] = [7777]
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("aborted", status.status)


class Test_v4_shp(VectorCheckTestCase):
    def test(self):
        # Unzip the datasource.
        from qc_tool.wps.vector_check.v_unzip import run_check as unzip_check
        zip_filepath = TEST_DATA_DIR.joinpath("vector", "ua_shp", "EE003L0_NARVA.shp.zip")
        self.params.update({"tmp_dir": self.params["jobdir_manager"].tmp_dir,
                            "filepath": zip_filepath})
        status = self.status_class()
        unzip_check(self.params, status)
        self.params["unzip_dir"] = status.params["unzip_dir"]

        # Run the check.
        from qc_tool.wps.vector_check.v4 import run_check
        shp_dir = self.params["unzip_dir"].joinpath("EE003L0_NARVA", "Shapefiles")
        reference_path = shp_dir.joinpath("EE003L0_NARVA_UA2012.shp")
        boundary_path = shp_dir.joinpath("Boundary2012_EE003L0_NARVA.shp")
        self.params.update({"layer_defs": {"boundary": {"src_filepath": boundary_path,
                                                        "src_layer_name": boundary_path.stem},
                                           "reference": {"src_filepath": reference_path,
                                                         "src_layer_name": reference_path.stem}},
                            "layers": ["boundary", "reference"],
                            "epsg": [3035],
                            "auto_identify_epsg": True})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)


class Test_v4_auto_identify_epsg(VectorCheckTestCase):
    def test(self):
        from qc_tool.wps.vector_check.v4 import run_check
        boundary_path = TEST_DATA_DIR.joinpath("vector", "ua_shp", "ES031L1_LUGO_boundary", "ES031L1_LUGO_UA2012_Boundary.shp")
        self.params.update({"layer_defs": {"boundary": {"src_filepath": boundary_path,
                                                        "src_layer_name": boundary_path.stem}},
                            "layers": ["boundary"],
                            "epsg": [3035],
                            "auto_identify_epsg": True})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)


class TestVImport2pg(VectorCheckTestCase):
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
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
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
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
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
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
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
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
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
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
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
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
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
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
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
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
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
        self.params.update({"layer_defs": {"layer_0": {"pg_layer_name": "mytable",
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
                            "layers": ["layer_0"]})
        run_check(self.params, status)
        self.assertEqual("failed", status.status)


class Test_v10(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.cursor = self.params["connection_manager"].get_connection().cursor()
        self.cursor.execute("CREATE TABLE boundary (wkb_geometry geometry(Polygon, 4326));")
        self.cursor.execute("INSERT INTO boundary VALUES (ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        self.cursor.execute("INSERT INTO boundary VALUES (ST_Difference(ST_MakeEnvelope(2, 2, 5, 5, 4326), ST_MakeEnvelope(3, 3, 4, 4, 4326)));")
        self.cursor.execute("CREATE TABLE reference (wkb_geometry geometry(Polygon, 4326));")
        self.params.update({"layer_defs": {"reference": {"pg_layer_name": "reference"},
                                           "boundary": {"pg_layer_name": "boundary"}},
                            "layers": ["reference"]})

    def test(self):
        from qc_tool.wps.vector_check.v10 import run_check
        self.cursor.execute("INSERT INTO reference VALUES (ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        self.cursor.execute("INSERT INTO reference VALUES (ST_MakeEnvelope(2, 2, 4, 5, 4326));")
        self.cursor.execute("INSERT INTO reference VALUES (ST_MakeEnvelope(4, 2, 5, 5, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.cursor.execute("SELECT * FROM v10_reference_error;")
        self.assertEqual(0, self.cursor.rowcount)

    def test_fail(self):
        from qc_tool.wps.vector_check.v10 import run_check
        self.cursor.execute("INSERT INTO reference VALUES (ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)
        self.cursor.execute("SELECT * FROM v10_reference_error;")
        self.assertEqual(1, self.cursor.rowcount)


class Test_v10_unit(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.cursor = self.params["connection_manager"].get_connection().cursor()
        self.cursor.execute("CREATE TABLE boundary (unit CHAR(1), wkb_geometry geometry(Polygon, 4326));")
        self.cursor.execute("INSERT INTO boundary VALUES ('A', ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        self.cursor.execute("INSERT INTO boundary VALUES ('A', ST_Difference(ST_MakeEnvelope(2, 2, 5, 5, 4326), ST_MakeEnvelope(3, 3, 4, 4, 4326)));")
        self.cursor.execute("INSERT INTO boundary VALUES ('B', ST_MakeEnvelope(6, 6, 7, 7, 4326));")
        self.cursor.execute("INSERT INTO boundary VALUES ('B', ST_MakeEnvelope(8, 8, 9, 9, 4326));")
        self.cursor.execute("INSERT INTO boundary VALUES ('C', ST_MakeEnvelope(10, 10, 11, 11, 4326));")
        self.cursor.execute("CREATE TABLE reference (unit CHAR(1), wkb_geometry geometry(Polygon, 4326));")
        self.params.update({"layer_defs": {"reference": {"pg_layer_name": "reference"},
                                           "boundary": {"pg_layer_name": "boundary"}},
                            "layers": ["reference"],
                            "boundary_unit_column_name": "unit"})

    def test(self):
        from qc_tool.wps.vector_check.v10_unit import run_check
        self.cursor.execute("INSERT INTO reference VALUES ('A', ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        self.cursor.execute("INSERT INTO reference VALUES ('A', ST_MakeEnvelope(2, 2, 4, 5, 4326));")
        self.cursor.execute("INSERT INTO reference VALUES ('A', ST_MakeEnvelope(4, 2, 5, 5, 4326));")
        self.cursor.execute("INSERT INTO reference VALUES ('B', ST_MakeEnvelope(6, 6, 9, 9, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.cursor.execute("SELECT * FROM v10_reference_error;")
        self.assertEqual(0, self.cursor.rowcount)

    def test_fail(self):
        from qc_tool.wps.vector_check.v10_unit import run_check
        self.cursor.execute("INSERT INTO reference VALUES ('A', ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        self.cursor.execute("INSERT INTO reference VALUES ('A', ST_MakeEnvelope(2, 2, 5, 5, 4326));")
        self.cursor.execute("INSERT INTO reference VALUES ('B', ST_MakeEnvelope(6, 6, 7, 7, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)
        self.cursor.execute("SELECT * FROM v10_reference_error;")
        self.assertEqual(1, self.cursor.rowcount)

    def test_warning(self):
        from qc_tool.wps.vector_check.v10_unit import run_check
        self.cursor.execute("INSERT INTO reference VALUES ('D', ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        self.cursor.execute("INSERT INTO reference VALUES (NULL, ST_MakeEnvelope(0, 0, 1, 1, 4326));")
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        self.cursor.execute("SELECT * FROM v10_reference_warning;")
        self.assertEqual(2, self.cursor.rowcount)


class Test_v11_clc_status(VectorCheckTestCase):
    def test(self):
        from qc_tool.wps.vector_check.v11_clc_status import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE reference (fid integer, shape_area real, wkb_geometry geometry(Polygon, 4326));")

        # General features.
        cursor.execute("INSERT INTO reference VALUES (10, 250001, ST_MakeEnvelope(10, 1, 11, 2, 4326));")
        cursor.execute("INSERT INTO reference VALUES (12, 250000, ST_MakeEnvelope(12, 0, 13, 2, 4326));")
        # Exception feature being at the boundary.
        cursor.execute("INSERT INTO reference VALUES (20, 249999, ST_MakeEnvelope(20, 0, 21, 2, 4326));")
        # Error feature.
        cursor.execute("INSERT INTO reference VALUES (30, 249999, ST_MakeEnvelope(10.1, 1.1, 10.9, 1.9, 4326));")

        self.params.update({"layer_defs": {"reference": {"pg_layer_name": "reference",
                                                         "pg_fid_name": "fid",
                                                         "fid_display_name": "row number"}},
                            "layers": ["reference"],
                            "area_column_name": "shape_area",
                            "area_m2": 250000})
        run_check(self.params, self.status_class())
        cursor.execute("SELECT fid FROM v11_reference_general ORDER BY fid;")
        self.assertListEqual([(10,), (12,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM v11_reference_exception ORDER BY fid;")
        self.assertListEqual([(20,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM v11_reference_error ORDER BY fid;")
        self.assertListEqual([(30,)], cursor.fetchall())


class Test_v11_clc_change(VectorCheckTestCase):
    def test(self):
        from qc_tool.wps.vector_check.v11_clc_change import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()

        # Artificial margin.
        cursor.execute("CREATE TABLE margin (wkb_geometry geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO margin VALUES (ST_MakeEnvelope(-1, -1, 100, 100, 4326));")

        # Add layer to be checked.
        cursor.execute("CREATE TABLE change (fid integer, shape_area real, code1 char(1), code2 char(1), wkb_geometry geometry(Polygon, 4326));")

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
                            "area_column_name": "shape_area",
                            "area_m2": 50000,
                            "initial_code_column_name": "code1",
                            "final_code_column_name": "code2"})
        run_check(self.params, self.status_class())
        cursor.execute("SELECT * FROM v11_change_general ORDER BY fid;")
        self.assertListEqual([(10,), (12,), (14,), (16,)], cursor.fetchall())
        cursor.execute("SELECT * FROM v11_change_exception ORDER BY fid;")
        self.assertListEqual([(20,), (22,), (23,), (25,), (26,)], cursor.fetchall())
        cursor.execute("SELECT * FROM v11_change_error ORDER BY fid;")
        self.assertListEqual([(30,), (32,), (33,)], cursor.fetchall())


class Test_v11_ua_status(VectorCheckTestCase):
    def test(self):
        from qc_tool.wps.vector_check.v11_ua_status import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE reference (fid integer, shape_area real, code char(5), wkb_geometry geometry(Polygon, 4326));")

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
                            "code_column_name": "code"})
        run_check(self.params, self.status_class())
        cursor.execute("SELECT fid FROM v11_reference_general ORDER BY fid;")
        self.assertListEqual([(10,), (12,), (14,), (16,), (18,), (20,), (22,), (24,), (26,), (28,), (30,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM v11_reference_exception ORDER BY fid;")
        self.assertListEqual([(40,), (42,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM v11_reference_warning ORDER BY fid;")
        self.assertListEqual([(50,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM v11_reference_error ORDER BY fid;")
        self.assertListEqual([(60,), (62,), (64,), (66,), (68,), (70,), (72,), (74,), (76,), (78,), (80,), (82,)], cursor.fetchall())


class Test_v11_ua_change(VectorCheckTestCase):
    def test(self):
        from qc_tool.wps.vector_check.v11_ua_change import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE change (fid integer, shape_area real, code1 char(5), code2 char(5), wkb_geometry geometry(Polygon, 4326));")

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
                            "final_code_column_name": "code2"})
        run_check(self.params, self.status_class())
        cursor.execute("SELECT fid FROM v11_change_general ORDER BY fid;")
        self.assertListEqual([(10,), (12,), (14,), (16,), (18,), (20,), (22,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM v11_change_exception ORDER BY fid;")
        self.assertListEqual([(30,), (32,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM v11_change_error ORDER BY fid;")
        self.assertListEqual([(40,), (42,), (44,), (46,), (48,), (50,), (52,), (54,), (56,), (58,), (60,), (62,)], cursor.fetchall())


class Test_v11_n2k(VectorCheckTestCase):
    def test(self):
        from qc_tool.wps.vector_check.v11_n2k import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE n2k (fid integer, area_ha real, code integer, wkb_geometry geometry(Polygon, 4326));")

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
                            "final_code_column_name": "code"})
        run_check(self.params, self.status_class())
        cursor.execute("SELECT fid FROM v11_n2k_general ORDER BY fid;")
        self.assertListEqual([(0,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM v11_n2k_exception ORDER BY fid;")
        self.assertListEqual([(10,), (20,), (21,), (22,), (23,), (24,), (30,), (40,), (41,), (42,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM v11_n2k_error ORDER BY fid;")
        self.assertListEqual([(11,), (25,)], cursor.fetchall())


class Test_v11_rpz(VectorCheckTestCase):
    def test(self):
        from qc_tool.wps.vector_check.v11_rpz import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE rpz (fid integer, area_ha real, code integer, ua char(1), wkb_geometry geometry(Polygon, 4326));")

        # Artificial margin as a general feature.
        cursor.execute("INSERT INTO rpz VALUES (0, 0.5, 10, NULL, ST_MakeEnvelope(-1, -1, 100, 100, 4326));")

        # Marginal features.
        cursor.execute("INSERT INTO rpz VALUES (10, 0.2, 8, NULL, ST_MakeEnvelope(-1, 0, 1, 1, 4326));")
        cursor.execute("INSERT INTO rpz VALUES (11, 0.1999, 8, NULL, ST_MakeEnvelope(-1, 2, 1, 3, 4326));")

        # Linear features.
        cursor.execute("INSERT INTO rpz VALUES (20, 0.1, 1211, NULL, ST_MakeEnvelope(0, 4, 1, 5, 4326));")
        cursor.execute("INSERT INTO rpz VALUES (21, 0.1, 1212, NULL, ST_MakeEnvelope(0, 6, 1, 7, 4326));")
        cursor.execute("INSERT INTO rpz VALUES (22, 0.1, 911, NULL, ST_MakeEnvelope(0, 8, 1, 9, 4326));")
        cursor.execute("INSERT INTO rpz VALUES (23, 0.1, 9111, NULL, ST_MakeEnvelope(0, 10, 1, 11, 4326));")
        cursor.execute("INSERT INTO rpz VALUES (24, 0.0999, 1211, NULL, ST_MakeEnvelope(0, 12, 1, 13, 4326));")
        cursor.execute("INSERT INTO rpz VALUES (25, 0.1, 2, NULL, ST_MakeEnvelope(0, 14, 1, 15, 4326));")

        # Feature covered by Urban Atlas Core Region.
        cursor.execute("INSERT INTO rpz VALUES (30, 0.25, 1, 'U', ST_MakeEnvelope(1, 16, 2, 17, 4326));")
        cursor.execute("INSERT INTO rpz VALUES (31, 0.2499, 1, 'U', ST_MakeEnvelope(1, 18, 2, 19, 4326));")

        self.params.update({"layer_defs": {"rpz": {"pg_layer_name": "rpz",
                                                   "pg_fid_name": "fid",
                                                   "fid_display_name": "row number"}},
                            "layers": ["rpz"],
                            "area_column_name": "area_ha",
                            "area_ha": 0.5,
                            "code_column_name": "code"})
        run_check(self.params, self.status_class())
        cursor.execute("SELECT fid FROM v11_rpz_general ORDER BY fid;")
        self.assertListEqual([(0,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM v11_rpz_exception ORDER BY fid;")
        self.assertListEqual([(10,), (20,), (21,), (22,), (23,), (30,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM v11_rpz_error ORDER BY fid;")
        self.assertListEqual([(11,), (24,), (25,), (31,)], cursor.fetchall())


class Test_v12(VectorCheckTestCase):
    def test(self):
        from qc_tool.wps.vector_check.v12 import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE mmw (fid integer, wkb_geometry geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO mmw VALUES (1, ST_MakeEnvelope(10, 10, 13, 11, 4326));")
        cursor.execute("INSERT INTO mmw VALUES (2, ST_MakeEnvelope(20, 20, 23, 23, 4326));")
        cursor.execute("INSERT INTO mmw VALUES (3, ST_Difference(ST_MakeEnvelope(30, 30, 39, 39, 4326),"
                                                               " ST_MakeEnvelope(33, 30, 36, 38, 4326)));")

        self.params.update({"layer_defs": {"mmw": {"pg_layer_name": "mmw",
                                                   "pg_fid_name": "fid",
                                                   "fid_display_name": "row number"}},
                            "layers": ["mmw"],
                            "mmw": 1.0})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        cursor.execute("SELECT fid FROM v12_mmw_warning ORDER BY fid;")
        self.assertListEqual([(1,), (3,)], cursor.fetchall())


class Test_v12_ua(VectorCheckTestCase):
    def test(self):
        from qc_tool.wps.vector_check.v12_ua import run_check
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE mmw (fid integer, code char(5), wkb_geometry geometry(Polygon, 4326));")
        cursor.execute("INSERT INTO mmw VALUES (1, '12', ST_MakeEnvelope(10, 10, 13, 11, 4326));")
        cursor.execute("INSERT INTO mmw VALUES (2, '12', ST_MakeEnvelope(20, 20, 23, 23, 4326));")
        cursor.execute("INSERT INTO mmw VALUES (3, '12', ST_Difference(ST_MakeEnvelope(30, 30, 39, 39, 4326),"
                                                                     " ST_MakeEnvelope(33, 30, 36, 38, 4326)));")
        cursor.execute("INSERT INTO mmw VALUES (4, '122', ST_MakeEnvelope(40, 40, 43, 41, 4326));")

        self.params.update({"layer_defs": {"mmw": {"pg_layer_name": "mmw",
                                                   "pg_fid_name": "fid",
                                                   "fid_display_name": "row number"}},
                            "layers": ["mmw"],
                            "code_column_name": "code",
                            "mmw": 1.0})
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)
        cursor.execute("SELECT fid FROM v12_mmw_exception ORDER BY fid;")
        self.assertListEqual([(4,)], cursor.fetchall())
        cursor.execute("SELECT fid FROM v12_mmw_warning ORDER BY fid;")
        self.assertListEqual([(1,), (3,)], cursor.fetchall())


class TestV13(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        cursor = self.params["connection_manager"].get_connection().cursor()
        cursor.execute("CREATE TABLE test_layer_1 (fid integer, wkb_geometry geometry(Polygon, 4326));")
        cursor.execute("CREATE TABLE test_layer_2 (fid integer, wkb_geometry geometry(Polygon, 4326));")
        self.params.update({"layer_defs": {"layer_1": {"pg_layer_name": "test_layer_1",
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"},
                                           "layer_2": {"pg_layer_name": "test_layer_2",
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
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
                                                       "pg_fid_name": "fid",
                                                       "fid_display_name": "row number"}},
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


class TestV15(VectorCheckTestCase):
    def setUp(self):
        super().setUp()
        self.xml_dir = TEST_DATA_DIR.joinpath("metadata")
        self.params["tmp_dir"] = self.params["jobdir_manager"].tmp_dir
        self.params["output_dir"] = self.params["jobdir_manager"].output_dir
        self.params["layers"] = ["layer0"]


    def test(self):
        from qc_tool.wps.vector_check.v15 import run_check
        self.params["layer_defs"] = {"layer0": {"src_filepath": self.xml_dir.joinpath("inspire-good.shp")}}
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("ok", status.status)

    def test_missing_xml_fail(self):
        from qc_tool.wps.vector_check.v15 import run_check
        self.params["layer_defs"] = {"layer0": {"src_filepath": self.xml_dir.joinpath("inspire-missing-metadata.gdb")}}
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)

    def test_fail(self):
        from qc_tool.wps.vector_check.v15 import run_check
        self.params["layer_defs"] = {"layer0": {"src_filepath": self.xml_dir.joinpath("inspire-bad.shp")}}
        status = self.status_class()
        run_check(self.params, status)
        self.assertEqual("failed", status.status)
        self.assertIn("inspire-bad_metadata_error.json", status.attachment_filenames)
