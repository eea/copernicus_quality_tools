from unittest.mock import patch

from django.http import JsonResponse
from django.test import RequestFactory
from django.test import SimpleTestCase
from django.urls import reverse

from qc_tool.frontend.dashboard.authentication import worker_token_required
from qc_tool.frontend.dashboard.authentication.decorators import (
    WORKER_AUTHENTICATE_HEADER,
)


class WorkerTokenRequiredTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.view_called = False

    def protected_view(self):
        @worker_token_required
        def view(request):
            self.view_called = True
            return JsonResponse({"status": "ok"})

        return view

    @patch(
        "qc_tool.frontend.dashboard.authentication.decorators.auth_worker"
    )
    def test_missing_token_is_rejected_before_authentication_and_view(
        self,
        auth,
    ):
        response = self.protected_view()(self.factory.get("/pull_job"))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response["WWW-Authenticate"],
            WORKER_AUTHENTICATE_HEADER,
        )
        self.assertEqual(response.content, b"")
        auth.assert_not_called()
        self.assertFalse(self.view_called)

    @patch(
        "qc_tool.frontend.dashboard.authentication.decorators.auth_worker",
        return_value=False,
    )
    def test_invalid_token_is_rejected_before_view(self, auth):
        response = self.protected_view()(
            self.factory.get("/pull_job", {"token": "invalid"})
        )

        self.assertEqual(response.status_code, 401)
        auth.assert_called_once_with("invalid")
        self.assertFalse(self.view_called)

    @patch(
        "qc_tool.frontend.dashboard.authentication.decorators.auth_worker",
        return_value=True,
    )
    def test_valid_query_token_allows_view(self, auth):
        response = self.protected_view()(
            self.factory.get("/pull_job", {"token": "valid"})
        )

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"status": "ok"})
        auth.assert_called_once_with("valid")
        self.assertTrue(self.view_called)


class PullJobAuthenticationIntegrationTests(SimpleTestCase):
    @patch("qc_tool.frontend.dashboard.views.models.pull_job")
    @patch(
        "qc_tool.frontend.dashboard.authentication.decorators.auth_worker"
    )
    def test_missing_token_cannot_reach_pull_job_view(self, auth, pull_job):
        response = self.client.get(reverse("pull_job"))

        self.assertEqual(response.status_code, 401)
        auth.assert_not_called()
        pull_job.assert_not_called()

    @patch("qc_tool.frontend.dashboard.views.models.pull_job")
    @patch(
        "qc_tool.frontend.dashboard.authentication.decorators.auth_worker",
        return_value=False,
    )
    def test_invalid_token_cannot_reach_pull_job_view(self, auth, pull_job):
        response = self.client.get(
            reverse("pull_job"),
            {"token": "invalid"},
        )

        self.assertEqual(response.status_code, 401)
        auth.assert_called_once_with("invalid")
        pull_job.assert_not_called()

    @patch(
        "qc_tool.frontend.dashboard.views.models.pull_job",
        return_value=None,
    )
    @patch(
        "qc_tool.frontend.dashboard.authentication.decorators.auth_worker",
        return_value=True,
    )
    def test_valid_query_token_reaches_pull_job_view(self, auth, pull_job):
        response = self.client.get(
            reverse("pull_job"),
            {"token": "valid"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, None)
        auth.assert_called_once_with("valid")
        pull_job.assert_called_once()
