#!/usr/bin/env python3


from unittest import TestCase


class TestProduct(TestCase):
    def test_load_product_definitions(self):
        from qc_tool.common import load_product_definitions
        product_definitions = load_product_definitions("clc")
        self.assertIn("checks", product_definitions)
        self.assertLess(1, len(product_definitions["checks"]))
        self.assertEqual({"check_ident": "clc.status.v1",
                          "parameters": {"formats": [".gdb"]},
                          "required": True},
                         product_definitions["checks"][0])

    def test_compile_product_infos(self):
        from qc_tool.common import compile_product_infos
        from qc_tool.wps.registry import load_all_check_functions
        load_all_check_functions()
        product_infos = compile_product_infos()
        self.assertIn("clc", product_infos)
        self.assertNotIn("clc.status", product_infos)
        self.assertIn("description", product_infos["clc"])
        self.assertEqual("CORINE Land Cover", product_infos["clc"]["description"])
        self.assertIn("checks", product_infos["clc"])
        self.assertLess(1, len(product_infos["clc"]["checks"]))
        self.assertEqual(("clc.change.v1", "File format is allowed.", True), product_infos["clc"]["checks"][0])
