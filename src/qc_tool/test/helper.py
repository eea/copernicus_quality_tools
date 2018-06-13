#!/usr/bin/env python3


from contextlib import ExitStack
from unittest import TestCase
from uuid import uuid4

from qc_tool.wps.manager import create_connection_manager
from qc_tool.wps.manager import create_jobdir_manager


class RasterCheckTestCase(TestCase):
    def setUp(self):
        self.job_uuid = str(uuid4())
        with ExitStack() as stack:
            self.jobdir_manager = stack.enter_context(create_jobdir_manager(self.job_uuid))
            self.addCleanup(stack.pop_all().close)


class VectorCheckTestCase(TestCase):
    def setUp(self):
        self.job_uuid = str(uuid4())
        with ExitStack() as stack:
             self.connection_manager = stack.enter_context(create_connection_manager(self.job_uuid))
             self.jobdir_manager = stack.enter_context(create_jobdir_manager(self.job_uuid))
             self.addCleanup(stack.pop_all().close)


