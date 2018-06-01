#!/usr/bin/env python3

from unittest import TestCase
from uuid import uuid4

from qc_tool.common import TEST_DATA_DIR
from qc_tool.wps.dispatch import dispatch

class Test_fty_YYYY_020m(TestCase):
    product_type_name = "fty_YYYY_020m"

    def test_bad_extension(self):
        filepath = TEST_DATA_DIR.joinpath("clc2012_mt.gdb")
        result = dispatch(str(uuid4()), filepath, self.product_type_name, [])
        self.assertEqual("aborted", result["r1"]["status"], "r1 should give aborted with bad extension.")
