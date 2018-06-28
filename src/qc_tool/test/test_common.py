#!/usr/bin/env python3


from pathlib import Path
from unittest import TestCase


class TestCommon(TestCase):
    def test_load_product_definition(self):
        from qc_tool.common import load_product_definition
        product_definition = load_product_definition("clc")
        self.assertIn("checks", product_definition)
        self.assertLess(1, len(product_definition["checks"]))
        self.assertEqual({"check_ident": "v1",
                          "parameters": {"formats": [".gdb"]},
                          "required": True},
                         product_definition["checks"][0])

    def test_get_product_descriptions(self):
        from qc_tool.common import get_product_descriptions
        product_descriptions = get_product_descriptions()
        self.assertIn("clc", product_descriptions)
        self.assertEqual("CORINE Land Cover", product_descriptions["clc"])

    def test_prepare_empty_job_status(self):
        from qc_tool.common import prepare_empty_job_status
        status = prepare_empty_job_status("clc")
        self.assertEqual("clc", status["product_ident"])
        self.assertEqual("CORINE Land Cover", status["description"])
        self.assertLess(4, len(status["checks"]))
        self.assertEqual("v1", status["checks"][0]["check_ident"])
        self.assertEqual("File format is allowed.", status["checks"][0]["check_description"])
        self.assertTrue(status["checks"][0]["required"])
        self.assertFalse(status["checks"][0]["system"])
        self.assertIsNone(status["checks"][0]["status"])
        self.assertIsNone(status["checks"][0]["message"])
        self.assertEqual("change.import2pg", status["checks"][4]["check_ident"])
        self.assertTrue(status["checks"][4]["system"])

class TestCommonWithConfig(TestCase):
    def setUp(self):
        from qc_tool.common import setup_config
        setup_config()

    def test_compose_job_dir(self):
        from qc_tool.common import compose_job_dir
        job_dir = compose_job_dir("abc-DEF-123")
        job_dir = str(job_dir)
        self.assertEqual("/mnt/qc_volume/work/job_abcdef123", job_dir)

    def test_compose_job_status_filepath(self):
        from qc_tool.common import compose_job_status_filepath
        job_status_filepath = compose_job_status_filepath("abc-DEF-123")
        job_status_filepath = str(job_status_filepath)
        self.assertEqual("/mnt/qc_volume/work/job_abcdef123/status.json", job_status_filepath)

    def test_compose_wps_status_filepath(self):
        from qc_tool.common import compose_wps_status_filepath
        wps_status_filepath = compose_wps_status_filepath("abc-DEF-123")
        wps_status_filepath = str(wps_status_filepath)
        self.assertEqual("/mnt/qc_volume/wps/output/abc-DEF-123.xml", wps_status_filepath)

    def test_get_all_wps_uuids(self):
        from qc_tool.common import get_all_wps_uuids
        Path("/mnt/qc_volume/wps/output").mkdir(parents=True)
        ok_filepath = Path("/mnt/qc_volume/wps/output/6ec51f46-0714-4644-9723-9a0cdbf9e52d.xml")
        ok_filepath.write_text("")
        wrong_filepath = Path("/mnt/qc_volume/wps/output/XXc51f46-0714-4644-9723-9a0cdbf9e52d.xml")
        wrong_filepath.write_text("")
        wps_uuids = get_all_wps_uuids()
        self.assertListEqual(["6ec51f46-0714-4644-9723-9a0cdbf9e52d"],
                             wps_uuids)
