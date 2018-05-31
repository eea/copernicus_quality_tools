#!/usr/bin/env python3

from os import environ
from unittest import TestCase
from uuid import uuid4


class TestDummyProductType(TestCase):
    def test_dummy(self):
        from qc_tool.wps.dispatch import dispatch
        result = dispatch(str(uuid4()), "non-existent-filename", "dummy", [])


class TestDummyCheck(TestCase):
    def test_dummy(self):
        pass
