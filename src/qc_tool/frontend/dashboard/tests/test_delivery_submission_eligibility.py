"""Submission eligibility contracts for a delivery's latest QC job."""

import json
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from qc_tool.common import JOB_FAILED
from qc_tool.common import JOB_OK
from qc_tool.common import JOB_RUNNING
from qc_tool.frontend.accounts.services.api_tokens import (
    issue_personal_access_token,
)
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.dashboard.models import S3Info


class DeliverySubmissionEligibilityTests(TestCase):
    """Only a deterministically latest successful QC job can be submitted."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="submission-eligibility-user",
            password="test-password",
        )

    def create_delivery(self, *, submitted=False):
        return Delivery.objects.create(
            user=self.user,
            filename="delivery.zip",
            size_bytes=1024,
            date_submitted=timezone.now() if submitted else None,
        )

    def create_job(
        self,
        *,
        delivery,
        status,
        created_at,
        job_uuid=None,
    ):
        values = {
            "delivery": delivery,
            "job_status": status,
            "date_created": created_at,
            "product_ident": "test-product",
            "product_description": "Test product",
        }
        if job_uuid is not None:
            values["job_uuid"] = job_uuid
        return Job.objects.create(**values)

    def test_latest_successful_job_is_submittable(self):
        now = timezone.now()
        delivery = self.create_delivery()
        self.create_job(
            delivery=delivery,
            status=JOB_FAILED,
            created_at=now - timedelta(hours=1),
        )
        latest = self.create_job(
            delivery=delivery,
            status=JOB_OK,
            created_at=now,
        )

        self.assertEqual(delivery.get_submittable_job(), latest)

    def test_older_success_does_not_override_a_newer_failed_or_running_job(self):
        for latest_status in (JOB_FAILED, JOB_RUNNING):
            with self.subTest(latest_status=latest_status):
                now = timezone.now()
                delivery = self.create_delivery()
                self.create_job(
                    delivery=delivery,
                    status=JOB_OK,
                    created_at=now - timedelta(hours=1),
                )
                self.create_job(
                    delivery=delivery,
                    status=latest_status,
                    created_at=now,
                )

                self.assertIsNone(delivery.get_submittable_job())

    def test_already_submitted_delivery_is_not_submittable_again(self):
        delivery = self.create_delivery(submitted=True)
        self.create_job(
            delivery=delivery,
            status=JOB_OK,
            created_at=timezone.now(),
        )

        self.assertIsNone(delivery.get_submittable_job())

    def test_soft_deleted_delivery_is_not_submittable(self):
        delivery = self.create_delivery()
        delivery.is_deleted = True
        delivery.save(update_fields=("is_deleted",))
        self.create_job(
            delivery=delivery,
            status=JOB_OK,
            created_at=timezone.now(),
        )

        self.assertIsNone(delivery.get_submittable_job())

    def test_equal_timestamps_use_descending_job_uuid_as_tie_breaker(self):
        created_at = timezone.now()

        successful_latest = self.create_delivery()
        self.create_job(
            delivery=successful_latest,
            status=JOB_FAILED,
            created_at=created_at,
            job_uuid=UUID(int=1),
        )
        expected = self.create_job(
            delivery=successful_latest,
            status=JOB_OK,
            created_at=created_at,
            job_uuid=UUID(int=2),
        )
        self.assertEqual(successful_latest.get_submittable_job(), expected)

        failed_latest = self.create_delivery()
        self.create_job(
            delivery=failed_latest,
            status=JOB_OK,
            created_at=created_at,
            job_uuid=UUID(int=3),
        )
        self.create_job(
            delivery=failed_latest,
            status=JOB_FAILED,
            created_at=created_at,
            job_uuid=UUID(int=4),
        )
        self.assertIsNone(failed_latest.get_submittable_job())

    def test_delivery_without_jobs_is_not_submittable(self):
        delivery = self.create_delivery()

        self.assertIsNone(delivery.get_submittable_job())


@override_settings(SUBMISSION_ENABLED=False)
class DisabledSubmissionEndpointTests(TestCase):
    """All submission transports fail closed before external side effects."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="disabled-submission-user",
            password="test-password",
        )
        self.client.force_login(self.user)
        s3 = S3Info.objects.create(
            host="https://s3.example.test",
            access_key="access-key",
            secret_key="secret-key",
            bucketname="bucket",
            key_prefix="deliveries",
        )
        self.delivery = Delivery.objects.create(
            user=self.user,
            filename="disabled-submission.zip",
            size_bytes=1024,
            s3=s3,
        )
        Job.objects.create(
            delivery=self.delivery,
            job_status=JOB_OK,
            date_created=timezone.now(),
            product_ident="test-product",
            product_description="Test product",
        )
        self.api_token = issue_personal_access_token(
            self.user,
            "Disabled submission endpoint tests",
        ).raw_token

    def assert_submission_disabled(self, response):
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {
                "status": "error",
                "code": "submission_disabled",
                "message": "Delivery submission is not enabled.",
            },
        )

    @patch("qc_tool.frontend.dashboard.views.deliveries.actions.submit_job")
    def test_session_single_submission_fails_closed(self, submit_job):
        response = self.client.post(
            reverse("delivery_submit"),
            {"id": str(self.delivery.pk)},
        )

        self.assert_submission_disabled(response)
        submit_job.assert_not_called()
        self.delivery.refresh_from_db()
        self.assertIsNone(self.delivery.date_submitted)

    @patch("qc_tool.frontend.dashboard.views.deliveries.actions.submit_job")
    def test_session_batch_submission_fails_closed(self, submit_job):
        response = self.client.post(
            reverse("delivery_submit_batch"),
            {"ids": str(self.delivery.pk)},
        )

        self.assert_submission_disabled(response)
        submit_job.assert_not_called()
        self.delivery.refresh_from_db()
        self.assertIsNone(self.delivery.date_submitted)

    @patch("qc_tool.frontend.dashboard.views.api_access.submissions.submit_job")
    def test_api_submission_fails_closed(self, submit_job):
        response = self.client.post(
            reverse("api_submit_delivery_to_eea"),
            data=json.dumps({"delivery_id": self.delivery.pk}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer {}".format(self.api_token),
        )

        self.assert_submission_disabled(response)
        submit_job.assert_not_called()
        self.delivery.refresh_from_db()
        self.assertIsNone(self.delivery.date_submitted)
