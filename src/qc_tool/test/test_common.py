#!/usr/bin/env python3


from unittest import TestCase


class TestCommon(TestCase):
    def test_load_product_definitions(self):
        from qc_tool.common import load_product_definitions
        product_definitions = load_product_definitions("clc")
        self.assertNotIn("checks", product_definitions[0])
        self.assertIn("checks", product_definitions[1])
        self.assertLess(1, len(product_definitions[1]["checks"]))
        self.assertEqual({"check_ident": "clc.change.v1",
                          "parameters": {"formats": [".gdb"]},
                          "required": True},
                         product_definitions[1]["checks"][0])

    def test_get_main_products(self):
        from qc_tool.common import get_main_products
        main_products = get_main_products()
        self.assertIn("clc", main_products)
        self.assertEqual("CORINE Land Cover", main_products["clc"])

    def test_prepare_empty_status(self):
        from qc_tool.common import prepare_empty_status
        status = prepare_empty_status("clc")
        self.assertEqual("clc", status["product_ident"])
        self.assertEqual("CORINE Land Cover", status["description"])
        self.assertLess(4, len(status["checks"]))
        self.assertEqual("clc.change.v1", status["checks"][0]["check_ident"])
        self.assertEqual("File format is allowed.", status["checks"][0]["check_description"])
        self.assertEqual("CORINE Land Cover, change layer", status["checks"][0]["product_description"])
        self.assertTrue(status["checks"][0]["required"])
        self.assertFalse(status["checks"][0]["system"])
        self.assertIsNone(status["checks"][0]["status"])
        self.assertIsNone(status["checks"][0]["message"])
        self.assertEqual("clc.change.import2pg", status["checks"][4]["check_ident"])
        self.assertTrue(status["checks"][4]["system"])
