#!/usr/bin/env python3


from pathlib import Path
from unittest import TestCase

from qc_tool.common import CONFIG


class TestCommon(TestCase):
    def test_load_product_definition(self):
        from qc_tool.common import load_product_definition
        product_definition = load_product_definition("clc_2012")
        self.assertIn("checks", product_definition)
        self.assertLess(1, len(product_definition["checks"]))
        self.assertDictEqual({"check_ident": "v2",
                              "parameters": {"layers": ["reference", "initial", "change"],
                                             "formats": [".gdb"],
                                             "drivers": {'.gdb': 'OpenFileGDB'}},
                              "required": True},
                             product_definition["checks"][2])

    def test_get_product_descriptions(self):
        from qc_tool.common import get_product_descriptions
        product_descriptions = get_product_descriptions()
        self.assertIn("clc_2012", product_descriptions)
        self.assertEqual("CORINE Land Cover 2012", product_descriptions["clc_2012"])

    def test_prepare_job_result(self):
        from qc_tool.common import prepare_job_result
        job_result = prepare_job_result("clc_2012")
        self.assertEqual("clc_2012", job_result["product_ident"])
        self.assertEqual("CORINE Land Cover 2012", job_result["description"])
        self.assertLess(4, len(job_result["steps"]))
        self.assertEqual("v2", job_result["steps"][2]["check_ident"])
        self.assertEqual("File format is correct.", job_result["steps"][2]["description"])
        self.assertTrue(job_result["steps"][1]["required"])
        self.assertFalse(job_result["steps"][1]["system"])
        self.assertIsNone(job_result["steps"][1]["status"])
        self.assertIsNone(job_result["steps"][1]["messages"])
        self.assertEqual("v_import2pg", job_result["steps"][7]["check_ident"])
        self.assertTrue(job_result["steps"][7]["system"])

class TestCommonWithConfig(TestCase):
    def setUp(self):
        from qc_tool.common import setup_config
        setup_config()
        CONFIG["wps_output_dir"].mkdir(exist_ok=True, parents=True)

    def test_compose_job_dir(self):
        from qc_tool.common import compose_job_dir
        job_dir = compose_job_dir("abc-DEF-123")
        job_dir = str(job_dir)
        self.assertEqual("/mnt/qc_tool_volume/work/job_abcdef123", job_dir)

    def test_compose_job_result_filepath(self):
        from qc_tool.common import compose_job_result_filepath
        job_result_filepath = compose_job_result_filepath("abc-DEF-123")
        job_result_filepath = str(job_result_filepath)
        self.assertEqual("/mnt/qc_tool_volume/work/job_abcdef123/result.json", job_result_filepath)

    def test_compose_wps_status_filepath(self):
        from qc_tool.common import compose_wps_status_filepath
        wps_status_filepath = compose_wps_status_filepath("abc-DEF-123")
        wps_status_filepath = str(wps_status_filepath)
        self.assertEqual("/mnt/qc_tool_volume/wps/output/abc-DEF-123.xml", wps_status_filepath)

    def test_get_all_wps_uuids(self):
        from qc_tool.common import get_all_wps_uuids
        ok_filepath = Path("/mnt/qc_tool_volume/wps/output/6ec51f46-0714-4644-9723-9a0cdbf9e52d.xml")
        ok_filepath.write_text("")
        wrong_filepath = Path("/mnt/qc_tool_volume/wps/output/XXc51f46-0714-4644-9723-9a0cdbf9e52d.xml")
        wrong_filepath.write_text("")
        wps_uuids = get_all_wps_uuids()
        self.assertListEqual(["6ec51f46-0714-4644-9723-9a0cdbf9e52d"],
                             wps_uuids)
