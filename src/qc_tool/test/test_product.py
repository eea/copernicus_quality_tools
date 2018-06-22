#!/usr/bin/env python3


from unittest import TestCase
from uuid import uuid4

from qc_tool.common import TEST_DATA_DIR
from qc_tool.wps.dispatch import dispatch


class Test_fty_YYYY_020m(TestCase):
    product_ident = "fty_YYYY_020m"

    def test_run(self):
        filepath = TEST_DATA_DIR.joinpath("fty_2015_020m_si_03035_d04_test.tif")
        result = dispatch(str(uuid4()), filepath, self.product_ident, [])
        self.assertEqual("ok", result["r1"]["status"],
                         "Slovenia test file should pass check for the product {:s}.".format(self.product_ident))

    def test_bad_extension(self):
        filepath = TEST_DATA_DIR.joinpath("clc2012_mt.gdb")
        result = dispatch(str(uuid4()), filepath, self.product_ident, [])
        self.assertEqual("aborted", result["r1"]["status"],
                         "r1 should give aborted with bad extension.")

class Test_clc_YY(TestCase):
    product_ident = "clc_YY"

    def test_run(self):
        filepath = TEST_DATA_DIR.joinpath("clc2012_mt.gdb")
        result = dispatch(str(uuid4()), filepath, self.product_ident, [])
        self.assertEqual("ok", result["v1"]["status"],
                         "Malta should pass the checks for the product {:s}.".format(self.product_ident))


class Test_update_status(TestCase):
    product_ident = "clc_YY"

    def test_run(self):
        def my_update(suite_result):
            print("-------UPDATE STATUS ------")
            print(suite_result)
        filepath = TEST_DATA_DIR.joinpath("clc2012_mt.gdb")
        dispatch(str(uuid4()), filepath, self.product_ident,
                 ["v1", "v2", "v3", "v4", "v5", "v6", "v8", "v11"], update_result_func=my_update)


