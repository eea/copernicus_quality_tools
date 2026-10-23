"""Maintenance browsing reads persisted facts without incidental updates."""

from datetime import timedelta
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from qc_tool.common import JOB_ERROR, JOB_RUNNING
from qc_tool.frontend.accounts.authentication.api_keys import authenticate_api_request
from qc_tool.frontend.accounts.authorization import access_for
from qc_tool.frontend.accounts.services.api_tokens import issue_personal_access_token
from qc_tool.frontend.dashboard.models import Delivery, Job
from qc_tool.frontend.dashboard.views.api_access.jobs import api_job_history
from qc_tool.frontend.dashboard.views.jobs.history import get_job_history_json
from qc_tool.frontend.dashboard.views.jobs.status import update_job


class MaintenanceReadTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = get_user_model().objects.create_superuser(
            username="maintenance-read-administrator", password="test-password",
        )
        self.delivery = Delivery.objects.create(
            user=self.user, filename="maintenance-read.zip", size_bytes=0,
            product_ident="maintenance-read",
        )
        self.job = Job.objects.create(
            delivery=self.delivery, job_status=JOB_RUNNING,
            product_ident="maintenance-read", product_description="Read-only test",
            date_started=timezone.now() - timedelta(minutes=5),
            worker_url="http://127.0.0.2:8000/",
        )

    def request(self, *, maintenance_active=True, method="get"):
        request = getattr(self.factory, method)("/maintenance-read-test")
        request.user = self.user
        request.api_access = access_for(self.user)
        request.maintenance_active = maintenance_active
        return request

    def call_without_writes(self, callback):
        with CaptureQueriesContext(connection) as queries:
            response = callback()
        mutations = [
            query["sql"] for query in queries
            if query["sql"].lstrip().upper().startswith(
                ("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER ", "DROP "),
            )
        ]
        self.assertEqual(mutations, [])
        return response

    @patch("qc_tool.frontend.dashboard.views.jobs.history.check_running_job", return_value=JOB_ERROR)
    def test_browser_history_preserves_running_job_without_contacting_worker(self, worker_status):
        request = self.request()
        response = self.call_without_writes(
            lambda: get_job_history_json(request, self.delivery.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)[0]["job_status"], JOB_RUNNING)
        worker_status.assert_not_called()
        self.job.refresh_from_db()
        self.assertEqual(self.job.job_status, JOB_RUNNING)
        self.assertIsNone(self.job.date_finished)

    @patch("qc_tool.frontend.dashboard.views.api_access.jobs.check_running_job", return_value=JOB_ERROR)
    def test_api_history_preserves_running_job_without_contacting_worker(self, worker_status):
        request = self.request()
        response = self.call_without_writes(
            lambda: api_job_history(request, self.delivery.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["data"][0]["job_status"], JOB_RUNNING)
        worker_status.assert_not_called()
        self.job.refresh_from_db()
        self.assertEqual(self.job.job_status, JOB_RUNNING)

    @patch("qc_tool.frontend.dashboard.views.jobs.status.check_running_job", return_value=JOB_ERROR)
    def test_status_poll_returns_persisted_state_without_refreshing_it(self, worker_status):
        request = self.request(method="post")
        response = self.call_without_writes(
            lambda: update_job(request, self.job.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["last_job_status"], JOB_RUNNING)
        worker_status.assert_not_called()
        self.job.refresh_from_db()
        self.assertEqual(self.job.job_status, JOB_RUNNING)

    def test_api_authentication_does_not_write_token_activity(self):
        issued = issue_personal_access_token(self.user, "Maintenance browsing")
        request = self.factory.get(
            "/api/jobs/history", HTTP_AUTHORIZATION="Bearer " + issued.raw_token,
        )
        request.maintenance_active = True

        result = self.call_without_writes(lambda: authenticate_api_request(request))

        self.assertTrue(result.is_authenticated)
        self.assertEqual(result.user.pk, self.user.pk)
        issued.token.refresh_from_db()
        self.assertIsNone(issued.token.last_used_at)

    def test_normal_api_authentication_still_records_token_activity(self):
        issued = issue_personal_access_token(self.user, "Normal browsing")
        request = self.factory.get(
            "/api/jobs/history", HTTP_AUTHORIZATION="Bearer " + issued.raw_token,
        )

        self.assertTrue(authenticate_api_request(request).is_authenticated)

        issued.token.refresh_from_db()
        self.assertIsNotNone(issued.token.last_used_at)

    @patch("qc_tool.frontend.dashboard.views.jobs.history.check_running_job", return_value=JOB_ERROR)
    def test_normal_history_still_refreshes_finished_jobs(self, worker_status):
        request = self.request(maintenance_active=False)

        response = get_job_history_json(request, self.delivery.pk)

        self.assertEqual(response.status_code, 200)
        worker_status.assert_called_once()
        self.job.refresh_from_db()
        self.assertEqual(self.job.job_status, JOB_ERROR)
        self.assertIsNotNone(self.job.date_finished)
