#!/usr/bin/env python3


from pathlib import Path
from unittest import TestCase


class TestCommon(TestCase):
    def test_load_product_definition(self):
        from qc_tool.common import load_product_definition
        product_definition = load_product_definition("clc_2012")
        self.assertIn("steps", product_definition)
        self.assertLess(1, len(product_definition["steps"]))
        self.assertDictEqual({"check_ident": "v2",
                              "parameters": {"layers": ["reference", "initial", "change"],
                                             "formats": [".gdb"],
                                             "drivers": {'.gdb': 'OpenFileGDB'}},
                              "required": True},
                             product_definition["steps"][2])

    def test_get_product_descriptions(self):
        from qc_tool.common import get_product_descriptions
        product_descriptions = get_product_descriptions()
        self.assertIn("clc_2012", product_descriptions)
        self.assertEqual("CORINE Land Cover 2012", product_descriptions["clc_2012"])

    def test_prepare_job_report(self):
        from qc_tool.common import load_product_definition
        from qc_tool.common import prepare_job_report
        product_definition = load_product_definition("clc_2012")
        job_result = prepare_job_report(product_definition)
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
        from qc_tool.common import CONFIG
        from qc_tool.common import setup_config
        setup_config()
        self.wps_output_dir = CONFIG["wps_output_dir"]
        self.wps_output_dir.mkdir(exist_ok=True, parents=True)
        self.work_dir = CONFIG["work_dir"]
        self.work_dir.mkdir(exist_ok=True, parents=True)

    def test_compose_job_dir(self):
        from qc_tool.common import compose_job_dir
        job_dir = compose_job_dir("job_uuid")
        self.assertEqual(Path(self.work_dir, "job_job_uuid"), job_dir)

    def test_store_load_job_result(self):
        from qc_tool.common import compose_job_dir
        from qc_tool.common import load_job_result
        from qc_tool.common import store_job_result
        job_uuid = "job_uuid_valu"
        job_dir = compose_job_dir(job_uuid)
        job_dir.mkdir(exist_ok=True)
        store_job_result({"job_uuid": job_uuid})
        self.assertDictEqual({"job_uuid": job_uuid}, load_job_result(job_uuid))

    def test_wps_status(self):
        from qc_tool.common import load_wps_status
        wps_status_filepath = self.wps_output_dir.joinpath("wps_status.xml")
        wps_status_filepath.write_text("wps status xml data")
        self.assertEqual("wps status xml data", load_wps_status("wps_status"))

    def test_get_all_wps_uuids(self):
        from qc_tool.common import get_all_wps_uuids
        ok_filepath = Path("/mnt/qc_tool_volume/wps/output/6ec51f46-0714-4644-9723-9a0cdbf9e52d.xml")
        ok_filepath.write_text("")
        wrong_filepath = Path("/mnt/qc_tool_volume/wps/output/XXc51f46-0714-4644-9723-9a0cdbf9e52d.xml")
        wrong_filepath.write_text("")
        wps_uuids = get_all_wps_uuids()
        self.assertListEqual(["6ec51f46-0714-4644-9723-9a0cdbf9e52d"],
                             wps_uuids)
