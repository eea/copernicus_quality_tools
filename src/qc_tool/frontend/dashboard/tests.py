# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from json import JSONDecodeError
from unittest.mock import patch

from django.test import TestCase

from qc_tool.common import JOB_FAILED
from qc_tool.common import JOB_OK
from qc_tool.common import JOB_RUNNING
from qc_tool.common import JOB_TIMEOUT
from qc_tool.common import JOB_WAITING
from qc_tool.frontend.dashboard.models import AOI_CODE_MAX_LENGTH
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import Job


class JobAoiPersistenceTests(TestCase):
    def setUp(self):
        self.delivery = Delivery.objects.create(filename="delivery.zip", size_bytes=1)

    def create_job(self, **kwargs):
        values = {
            "delivery": self.delivery,
            "product_ident": "clc2012",
            "product_description": "CORINE Land Cover 2012",
        }
        values.update(kwargs)
        return Job.objects.create(**values)

    @patch("qc_tool.frontend.dashboard.models.load_job_result")
    def test_terminal_status_persists_aoi_code(self, load_result):
        load_result.return_value = {"aoi_code": "mt"}
        job = self.create_job()

        job.update_status(JOB_OK)

        job.refresh_from_db()
        self.assertEqual(JOB_OK, job.job_status)
        self.assertEqual("mt", job.aoi_code)
        self.assertIsNotNone(job.date_finished)
        load_result.assert_called_once_with(str(job.job_uuid))

    @patch("qc_tool.frontend.dashboard.models.load_job_result")
    def test_failed_status_also_persists_aoi_code(self, load_result):
        load_result.return_value = {"aoi_code": "E73N22"}
        job = self.create_job()

        job.update_status(JOB_FAILED)

        job.refresh_from_db()
        self.assertEqual(JOB_FAILED, job.job_status)
        self.assertEqual("e73n22", job.aoi_code)

    @patch("qc_tool.frontend.dashboard.models.load_job_result")
    def test_nonterminal_status_does_not_load_result_metadata(self, load_result):
        for job_status in (JOB_WAITING, JOB_RUNNING):
            with self.subTest(job_status=job_status):
                job = self.create_job()
                job.update_status(job_status)
                job.refresh_from_db()
                self.assertEqual(job_status, job.job_status)
                self.assertIsNone(job.aoi_code)
                self.assertIsNone(job.date_finished)
        load_result.assert_not_called()

    def test_unreadable_result_does_not_block_terminal_status(self):
        errors = (
            FileNotFoundError("result not found"),
            JSONDecodeError("invalid result", "", 0),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__):
                job = self.create_job()
                with patch("qc_tool.frontend.dashboard.models.load_job_result", side_effect=error):
                    job.update_status(JOB_TIMEOUT)
                job.refresh_from_db()
                self.assertEqual(JOB_TIMEOUT, job.job_status)
                self.assertIsNone(job.aoi_code)
                self.assertIsNotNone(job.date_finished)

    def test_invalid_aoi_metadata_is_ignored(self):
        invalid_results = (
            [],
            {},
            {"aoi_code": None},
            {"aoi_code": ""},
            {"aoi_code": 123},
            {"aoi_code": "x" * (AOI_CODE_MAX_LENGTH + 1)},
        )
        for result in invalid_results:
            with self.subTest(result=result):
                job = self.create_job()
                self.assertEqual([], job.apply_result_metadata(result))
                self.assertIsNone(job.aoi_code)

    @patch("qc_tool.frontend.dashboard.models.load_job_result")
    def test_missing_metadata_does_not_erase_persisted_aoi(self, load_result):
        load_result.return_value = {}
        job = self.create_job(aoi_code="mt")

        job.update_status(JOB_FAILED)

        job.refresh_from_db()
        self.assertEqual("mt", job.aoi_code)

    @patch("qc_tool.frontend.dashboard.models.load_job_result")
    def test_explicit_null_metadata_clears_persisted_aoi(self, load_result):
        load_result.return_value = {"aoi_code": None}
        job = self.create_job(aoi_code="mt")

        job.update_status(JOB_FAILED)

        job.refresh_from_db()
        self.assertIsNone(job.aoi_code)

    @patch("qc_tool.frontend.dashboard.models.load_job_result")
    def test_date_finished_is_write_once(self, load_result):
        load_result.return_value = {"aoi_code": "mt"}
        job = self.create_job()
        job.update_status(JOB_OK)
        job.refresh_from_db()
        first_finished = job.date_finished

        job.update_status(JOB_FAILED)

        job.refresh_from_db()
        self.assertEqual(first_finished, job.date_finished)
