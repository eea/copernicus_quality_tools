#!/usr/bin/env python3


from unittest import TestCase


class TestProduct(TestCase):
    def test_load_product_definition(self):
        from qc_tool.common import load_product_definition
        product_definition = load_product_definition("clc_YY")
        print(product_definition)

    def test_compile_product_infos(self):
        from qc_tool.common import compile_product_infos
        from qc_tool.wps.registry import load_all_check_functions
        load_all_check_functions()
        product_infos = compile_product_infos()
        print(product_infos)
