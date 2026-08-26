"""Regression tests for delivery-to-job navigation and association."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from qc_tool.common import JOB_FAILED
from qc_tool.common import JOB_OK
from qc_tool.frontend.accounts.services.api_tokens import (
    issue_personal_access_token,
)
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import Job


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class JobHistoryAssociationTests(TestCase):
    """A delivery history is keyed by identity, never by a filename."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="job-history-association-user",
            password="test-password",
        )
        self.client.force_login(self.user)

    def test_duplicate_filenames_do_not_merge_distinct_delivery_histories(self):
        now = timezone.now()
        first = Delivery.objects.create(
            user=self.user,
            filename="duplicate-name.zip",
            size_bytes=1024,
        )
        second = Delivery.objects.create(
            user=self.user,
            filename="duplicate-name.zip",
            size_bytes=2048,
        )
        older_first_job = Job.objects.create(
            delivery=first,
            date_created=now - timedelta(minutes=2),
            job_status=JOB_FAILED,
            product_ident="FIRST",
            product_description="First product",
        )
        latest_first_job = Job.objects.create(
            delivery=first,
            date_created=now - timedelta(minutes=1),
            job_status=JOB_OK,
            product_ident="FIRST",
            product_description="First product",
        )
        second_job = Job.objects.create(
            delivery=second,
            date_created=now,
            job_status=JOB_OK,
            product_ident="SECOND",
            product_description="Second product",
        )

        response = self.client.get(
            reverse("job_history_json", args=(first.pk,))
        )

        self.assertEqual(response.status_code, 200)
        job_ids = [row["job_uuid"] for row in response.json()]
        self.assertEqual(
            job_ids,
            [str(latest_first_job.job_uuid), str(older_first_job.job_uuid)],
        )
        self.assertNotIn(str(second_job.job_uuid), job_ids)

        issued = issue_personal_access_token(
            self.user,
            "Duplicate filename history regression",
        )
        api_response = self.client.get(
            reverse("api_job_history", args=(first.pk,)),
            HTTP_AUTHORIZATION=f"Bearer {issued.raw_token}",
        )

        self.assertEqual(api_response.status_code, 200)
        api_job_ids = [row["job_uuid"] for row in api_response.json()["data"]]
        self.assertEqual(
            api_job_ids,
            [latest_first_job.job_uuid.hex, older_first_job.job_uuid.hex],
        )
        self.assertNotIn(second_job.job_uuid.hex, api_job_ids)
