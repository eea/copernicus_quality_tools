#!/usr/bin/env python3


from contextlib import closing
from contextlib import ExitStack
from unittest import TestCase
from uuid import uuid4

from qc_tool.wps.dispatch import CheckStatus
from qc_tool.wps.manager import create_connection_manager
from qc_tool.wps.manager import create_jobdir_manager
from qc_tool.wps.registry import load_all_check_functions


class ProductTestCase(TestCase):
    def setUp(self):
        super().setUp()
        load_all_check_functions()
        self.job_uuid = str(uuid4())


class RasterCheckTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.status_class = CheckStatus
        job_uuid = str(uuid4())
        with ExitStack() as stack:
            self.jobdir_manager = stack.enter_context(create_jobdir_manager(job_uuid))
            self.addCleanup(stack.pop_all().close)


class VectorCheckTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.status_class = CheckStatus
        job_uuid = str(uuid4())
        self.params = {}
        with ExitStack() as stack:
             self.params["connection_manager"] = stack.enter_context(create_connection_manager(job_uuid))
             self.params["jobdir_manager"] = stack.enter_context(create_jobdir_manager(job_uuid))
             self.addCleanup(stack.pop_all().close)
