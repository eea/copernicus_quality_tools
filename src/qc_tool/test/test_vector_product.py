#!/usr/bin/env python3


import json
from pathlib import Path

from qc_tool.common import TEST_DATA_DIR
from qc_tool.common import compose_attachment_filepath
from qc_tool.common import compose_job_status_filepath
from qc_tool.test.helper import ProductTestCase
from qc_tool.wps.dispatch import dispatch


class Test_clc(ProductTestCase):
    def test(self):
        from qc_tool.common import CONFIG
        CONFIG["boundary_dir"] = TEST_DATA_DIR.joinpath("boundaries")
        filepath = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb.zip")
        job_status = dispatch(self.job_uuid,
                              "user_name",
                              filepath,
                              "clc_2012",
                              ["v5",
                               "reference.v6",
                               "initial.v6",
                               "change.v6",
                               "v8",
                               "v11_clc_status",
                               "v11_clc_change",
                               "v13",
                               "reference.v14",
                               "initial.v14",
                               "change.v14",
                               "v15"])

        statuses_ok = [check for check in job_status["checks"] if check["status"] == "ok"]
        checks_not_ok = [check["check_ident"] for check in job_status["checks"] if check["status"] != "ok"]

        self.assertEqual(len(statuses_ok), len(job_status["checks"]),
                         "Checks {:s} do not have status ok.".format(",".join(checks_not_ok)))


class Test_clc_status(ProductTestCase):
    def test_status_json(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "clc", "clc2012_mt.gdb.zip")
        status_filepath = compose_job_status_filepath(self.job_uuid)
        job_status = dispatch(self.job_uuid, "user_name", filepath, "clc_2012", [])
        self.assertTrue(status_filepath.exists())
        job_status_from_file = status_filepath.read_text()
        job_status_from_file = json.loads(job_status_from_file)
        self.assertEqual(job_status, job_status_from_file,
                         "Job status returned by dispatch() must be the same as stored in status.json file.")


class Test_n2k(ProductTestCase):
    def test(self):
        self.filepath = TEST_DATA_DIR.joinpath("vector", "n2k", "n2k_example_cz_correct.zip")
        expected_check_statuses = {"v_unzip": "ok",
                                   "v1_n2k": "ok",
                                   "v2": "ok",
                                   "v3": "ok",
                                   "v4": "ok",
                                   "v_import2pg": "ok",
                                   "v5": "ok",
                                   "v6": "ok",
                                   "v8": "ok",
                                   "v11_n2k": "ok",
                                   "v13": "ok",
                                   "v14": "ok",
                                   "v15": "ok"}
        job_status = dispatch(self.job_uuid,
                              "user_name",
                              self.filepath,
                              "n2k",
                              ["v5", "v6", "v8", "v11_n2k", "v13", "v14", "v15"])
        check_statuses = dict((check_status["check_ident"], check_status["status"])
                              for check_status in job_status["checks"])
        self.assertDictEqual(expected_check_statuses, check_statuses)

    def test_fail(self):
        self.filepath = TEST_DATA_DIR.joinpath("vector", "n2k", "n2k_example_cz_wrong.zip")
        expected_check_statuses = {"v_unzip": "ok",
                                   "v1_n2k": "ok",
                                   "v2": "ok",
                                   "v3": "ok",
                                   "v4": "ok",
                                   "v_import2pg": "ok",
                                   "v5": "ok",
                                   "v6": "failed", # a delivery with old version of n2k MAES codes should fail.
                                   "v8": "ok",
                                   "v11_n2k": "ok",
                                   "v13": "ok",
                                   "v14": "ok",
                                   "v15": "ok"}
        job_status = dispatch(self.job_uuid,
                              "user_name",
                              self.filepath,
                              "n2k",
                              ["v5", "v6", "v8", "v11_n2k", "v13", "v14", "v15"])
        check_statuses = dict((check_status["check_ident"], check_status["status"])
                              for check_status in job_status["checks"])
        self.assertDictEqual(expected_check_statuses, check_statuses)


class Test_rpz(ProductTestCase):
    def test(self):
        self.filepath = TEST_DATA_DIR.joinpath("vector", "rpz", "RPZ_LCLU_DU032B_clip2.zip")
        expected_check_statuses = {"v_unzip": "ok",
                                   "v1_rpz": "ok",
                                   "v2": "ok",
                                   "v3": "ok",
                                   "v4": "ok",
                                   "v_import2pg": "ok",
                                   "v5": "ok",
                                   "v6": "ok",
                                   "v8": "ok",
                                   "v11_rpz": "ok",
                                   "v13": "ok",
                                   "v14": "ok",
                                   "v15": "ok"}
        job_status = dispatch(self.job_uuid,
                              "user_name",
                              self.filepath,
                              "rpz",
                              ["v5", "v6", "v8", "v11_rpz", "v13", "v14", "v15"])
        check_statuses = dict((check_status["check_ident"], check_status["status"])
                              for check_status in job_status["checks"])
        self.assertDictEqual(expected_check_statuses, check_statuses)

    def test_inside_ua_core(self):
        self.filepath = TEST_DATA_DIR.joinpath("vector", "rpz", "RPZ_LCLU_DU032A_clip1.zip")
        expected_check_statuses = {"v_unzip": "ok",
                                   "v1_rpz": "ok",
                                   "v2": "ok",
                                   "v3": "ok",
                                   "v4": "ok",
                                   "v_import2pg": "ok",
                                   "v5": "ok",
                                   "v6": "ok",
                                   "v8": "ok",
                                   "v11_rpz": "failed", #the dataset contains very small polygons < 0.2ha touching border.
                                   "v13": "ok",
                                   "v14": "failed", # FIXME? neighbouring road polygons in UA core region
                                   "v15": "ok"}
        job_status = dispatch(self.job_uuid,
                              "user_name",
                              self.filepath,
                              "rpz",
                              ["v5", "v6", "v8", "v11_rpz", "v13", "v14", "v15"])
        check_statuses = dict((check_status["check_ident"], check_status["status"])
                              for check_status in job_status["checks"])
        self.assertDictEqual(expected_check_statuses, check_statuses)


class Test_ua_shp(ProductTestCase):
    def test(self):
        self.filepath = TEST_DATA_DIR.joinpath("vector", "ua_shp", "EE003L0_NARVA.shp.zip")
        expected_check_statuses = {"v_unzip": "ok",
                                   "v1_ua_shp": "ok",
                                   "v2": "ok",
                                   "reference.v3": "ok",
                                   "boundary.v3": "ok",
                                   "v4": "ok",
                                   "v_import2pg": "ok",
                                   "v5": "ok",
                                   "v6": "ok",
                                   "v8": "ok",
                                   "v11_ua_status": "ok",
                                   "v13": "ok",
                                   "v14": "ok",
                                   "v15": "failed" #FIXME provide INSPIRE-compliant UA metadata file.
                                   }
        job_status = dispatch(self.job_uuid,
                              "user_name",
                              self.filepath,
                              "ua_2012_shp_wo_revised",
                              ["v5", "v6", "v8", "v11_ua_status", "v13", "v14", "v15"])
        check_statuses = dict((check_status["check_ident"], check_status["status"])
                              for check_status in job_status["checks"])
        self.assertDictEqual(expected_check_statuses, check_statuses)


class Test_ua_gdb(ProductTestCase):
    def test_klagenfurt(self):
        # FIXME:
        # Klagenfurt test zip should be removed while it fails in some checks.
        # The new test zip should pass all checks with ok status.
        filepath = TEST_DATA_DIR.joinpath("vector", "ua_gdb", "AT006L1_KLAGENFURT.zip")
        expected_check_statuses = {"v_unzip": "ok",
                                   "v1_ua_gdb": "ok",
                                   "v2": "ok",
                                   "reference.v3": "ok",
                                   "boundary.v3": "ok",
                                   "v4": "ok",
                                   "v_import2pg": "ok",
                                   "v5": "ok",
                                   "v6": "ok",
                                   "v8": "ok",
                                   "v11_ua_status": "failed",
                                   "v13": "failed",
                                   "v14": "ok"}
        job_status = dispatch(self.job_uuid,
                              "user_name",
                              filepath,
                              "ua_2012_gdb_wo_revised",
                              ["v5", "v6", "v8", "v11_ua_status", "v13", "v14"])
        check_statuses = dict((check_status["check_ident"], check_status["status"])
                              for check_status in job_status["checks"])
        self.assertDictEqual(expected_check_statuses, check_statuses)

    def test_kobenhavn(self):
        self.maxDiff = None
        filepath = TEST_DATA_DIR.joinpath("vector", "ua_gdb", "DK001L2_KOBENHAVN_clip.zip")
        expected_check_statuses = {"v_unzip": "ok",
                                   "v1_ua_gdb": "ok",
                                   "v2": "ok",
                                   "reference.v3": "ok",
                                   "boundary.v3": "ok",
                                   "revised.v3": "ok",
                                   "combined_change.v3": "ok",
                                   "v4": "ok",
                                   "v_import2pg": "ok",
                                   "v5": "ok",
                                   "reference.v6": "ok",
                                   "revised.v6": "ok",
                                   "combined_change.v6": "ok",
                                   "v8": "ok",
                                   "reference.v11_ua_status": "ok",
                                   "revised.v11_ua_status": "ok",
                                   "change.v11_ua_change": "ok",
                                   "v13": "ok",
                                   "reference.v14": "ok",
                                   "revised.v14": "ok",
                                   "combined_change.v14": "ok"}
        job_status = dispatch(self.job_uuid,
                              "user_name",
                              filepath,
                              "ua_2012_gdb",
                              ["v5",
                               "reference.v6",
                               "revised.v6",
                               "combined_change.v6",
                               "v8",
                               "reference.v11_ua_status",
                               "revised.v11_ua_status",
                               "change.v11_ua_change",
                               "v13",
                               "reference.v14",
                               "revised.v14",
                               "combined_change.v14"])
        check_statuses = dict((check_status["check_ident"], check_status["status"])
                              for check_status in job_status["checks"])
        self.assertDictEqual(expected_check_statuses, check_statuses)


class Test_dump_error_table(ProductTestCase):
    def test(self):
        filepath = TEST_DATA_DIR.joinpath("vector", "ua_gdb", "AT006L1_KLAGENFURT.zip")
        expected_check_statuses = {"v_unzip": "ok",
                                   "v1_ua_gdb": "ok",
                                   "v2": "ok",
                                   "reference.v3": "ok",
                                   "boundary.v3": "ok",
                                   "v4": "ok",
                                   "v_import2pg": "ok",
                                   "v5": "skipped",
                                   "v6": "skipped",
                                   "v8": "skipped",
                                   "v11_ua_status": "skipped",
                                   "v13": "failed",
                                   "v14": "skipped"}
        job_status = dispatch(self.job_uuid,
                              "user_name",
                              filepath,
                              "ua_2012_gdb_wo_revised",
                              ["v13"])
        check_statuses = dict((check_status["check_ident"], check_status["status"]) for check_status in job_status["checks"])
        self.assertDictEqual(expected_check_statuses, check_statuses)
        zip_filepath = compose_attachment_filepath(job_status["job_uuid"], "v13_at006l1_klagenfurt_ua2012_error.zip")
        self.assertTrue(zip_filepath.is_file())
