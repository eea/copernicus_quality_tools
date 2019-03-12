#!/usr/bin/env python3


from unittest import TestCase

from qc_tool.common import QCException


class TestValidateSkipSteps(TestCase):
    def setUp(self):
        self.product_definition = {"steps": [{"required": True}, {"required": False}]}

    def test(self):
        from qc_tool.worker.dispatch import validate_skip_steps
        validate_skip_steps([2], self.product_definition)

    def test_out_of_range(self):
        from qc_tool.worker.dispatch import validate_skip_steps
        self.assertRaisesRegex(QCException, "Skip step 3 is out of range.", validate_skip_steps, [3], self.product_definition)
        self.assertRaisesRegex(QCException, "Skip step 0 is out of range.", validate_skip_steps, [0], self.product_definition)

    def test_duplicit(self):
        from qc_tool.worker.dispatch import validate_skip_steps
        self.assertRaisesRegex(QCException, "Duplicit skip step 2.", validate_skip_steps, [2, 2], self.product_definition)

    def test_required(self):
        from qc_tool.worker.dispatch import validate_skip_steps
        self.assertRaisesRegex(QCException, "Required step 1 can not be skipped.", validate_skip_steps, [1], self.product_definition)
