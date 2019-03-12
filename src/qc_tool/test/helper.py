#!/usr/bin/env python3


from contextlib import ExitStack
from unittest import TestCase
from uuid import uuid4

from qc_tool.common import CONFIG
from qc_tool.common import TEST_DATA_DIR
from qc_tool.worker.dispatch import CheckStatus
from qc_tool.worker.manager import create_connection_manager
from qc_tool.worker.manager import create_jobdir_manager


class ProductTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.job_uuid = str(uuid4())

        # Set up boundary dir to testing sources.
        CONFIG["boundary_dir"] = TEST_DATA_DIR.joinpath("boundaries")

        # online INSPIRE validator is skipped in tests.
        CONFIG["skip_inspire_check"] = True


class RasterCheckTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.status_class = CheckStatus
        job_uuid = str(uuid4())
        self.params = {}
        with ExitStack() as stack:
            self.jobdir_manager = stack.enter_context(create_jobdir_manager(job_uuid))
            self.addCleanup(stack.pop_all().close)
            self.params["skip_inspire_check"] = True


class VectorCheckTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.status_class = CheckStatus
        job_uuid = str(uuid4())
        self.params = {}
        with ExitStack() as stack:
             self.params["connection_manager"] = stack.enter_context(create_connection_manager(job_uuid))
             self.params["jobdir_manager"] = stack.enter_context(create_jobdir_manager(job_uuid))

             self.params["skip_inspire_check"] = True
             self.addCleanup(stack.pop_all().close)
