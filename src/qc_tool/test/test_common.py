#!/usr/bin/env python3


from contextlib import ExitStack
from pathlib import Path
from unittest import TestCase
from uuid import uuid4

from qc_tool.worker.manager import create_jobdir_manager


class TestCommon(TestCase):
    def test_load_product_definition(self):
        from qc_tool.common import load_product_definition
        product_definition = load_product_definition("clc_2012")
        self.assertIn("steps", product_definition)
        self.assertLess(1, len(product_definition["steps"]))
        self.assertDictEqual({"check_ident": "qc_tool.vector.format",
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

    def test_prepare_job_blueprint(self):
        from qc_tool.common import load_product_definition
        from qc_tool.common import prepare_job_blueprint
        product_definition = load_product_definition("clc_2012")
        job_result = prepare_job_blueprint(product_definition)
        self.assertEqual("clc_2012", job_result["product_ident"])
        self.assertEqual("CORINE Land Cover 2012", job_result["description"])
        self.assertLess(4, len(job_result["steps"]))
        self.assertEqual("qc_tool.vector.format", job_result["steps"][2]["check_ident"])
        self.assertEqual("Delivery content uses specific file format.", job_result["steps"][2]["description"])
        self.assertTrue(job_result["steps"][1]["required"])
        self.assertFalse(job_result["steps"][1]["system"])
        self.assertIsNone(job_result["steps"][1]["status"])
        self.assertIsNone(job_result["steps"][1]["messages"])
        self.assertEqual("qc_tool.vector.import2pg", job_result["steps"][7]["check_ident"])
        self.assertTrue(job_result["steps"][7]["system"])


class TestProductDirs(TestCase):
    def setUp(self):
        super().setUp()
        from qc_tool.common import CONFIG
        self.orig_product_dirs = CONFIG["product_dirs"]
        job_uuid = str(uuid4())
        with ExitStack() as stack:
            self.jobdir_manager = stack.enter_context(create_jobdir_manager(job_uuid))
            self.addCleanup(stack.pop_all().close)

        self.product_dir_1 = self.jobdir_manager.tmp_dir.joinpath("products_1")
        self.product_dir_1.mkdir()
        self.product_dir_1.joinpath("p1.json").write_text('{"description": "p1desc"}')
        self.product_dir_1.joinpath("pX.json").write_text('{"description": "pXdesc from 1"}')

        self.product_dir_2 = self.jobdir_manager.tmp_dir.joinpath("products_2")
        self.product_dir_2.mkdir()
        self.product_dir_2.joinpath("p2.json").write_text('{"description": "p2desc"}')
        self.product_dir_2.joinpath("pX.json").write_text('{"description": "pXdesc from 2"}')

    def tearDown(self):
        from qc_tool.common import CONFIG
        CONFIG["product_dirs"] = self.orig_product_dirs
        super().tearDown()

    def test_locate_product_definition(self):
        from qc_tool.common import CONFIG
        from qc_tool.common import locate_product_definition

        CONFIG["product_dirs"] = [self.product_dir_1, self.product_dir_2]
        self.assertEqual(self.product_dir_1.joinpath("p1.json"), locate_product_definition("p1"))
        self.assertEqual(self.product_dir_2.joinpath("p2.json"), locate_product_definition("p2"))
        self.assertEqual(self.product_dir_1.joinpath("pX.json"), locate_product_definition("pX"))

        CONFIG["product_dirs"] = [self.product_dir_2, self.product_dir_1]
        self.assertEqual(self.product_dir_1.joinpath("p1.json"), locate_product_definition("p1"))
        self.assertEqual(self.product_dir_2.joinpath("p2.json"), locate_product_definition("p2"))
        self.assertEqual(self.product_dir_2.joinpath("pX.json"), locate_product_definition("pX"))

    def test_get_product_descriptions(self):
        from qc_tool.common import CONFIG
        from qc_tool.common import get_product_descriptions

        CONFIG["product_dirs"] = [self.product_dir_1, self.product_dir_2]
        self.assertDictEqual({"p1": "p1desc", "p2": "p2desc", "pX": "pXdesc from 1"}, get_product_descriptions())

        CONFIG["product_dirs"] = [self.product_dir_2, self.product_dir_1]
        self.assertDictEqual({"p1": "p1desc", "p2": "p2desc", "pX": "pXdesc from 2"}, get_product_descriptions())


class TestCommonWithConfig(TestCase):
    def setUp(self):
        from qc_tool.common import CONFIG
        from qc_tool.common import setup_config
        setup_config()
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
