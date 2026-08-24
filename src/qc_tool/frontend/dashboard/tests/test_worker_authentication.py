from unittest.mock import patch

from django.http import JsonResponse
from django.test import RequestFactory
from django.test import SimpleTestCase
from django.urls import reverse

from qc_tool.frontend.dashboard.authentication import worker_token_required
from qc_tool.frontend.dashboard.authentication.decorators import (
    WORKER_AUTHENTICATE_HEADER,
    WORKER_AUTH_SCHEME,
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
        response = self.protected_view()(self.factory.post("/pull_job"))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response["WWW-Authenticate"],
            WORKER_AUTHENTICATE_HEADER,
        )
        self.assertEqual(response.content, b"")
        self.assertEqual(response["Cache-Control"], "no-store, private")
        self.assertEqual(response["Pragma"], "no-cache")
        self.assertEqual(response["Vary"], "Authorization")
        auth.assert_not_called()
        self.assertFalse(self.view_called)

    @patch(
        "qc_tool.frontend.dashboard.authentication.decorators.auth_worker",
        return_value=False,
    )
    def test_query_string_token_is_not_accepted(self, auth):
        response = self.protected_view()(
            self.factory.post("/pull_job?token=legacy-query-token")
        )

        self.assertEqual(response.status_code, 401)
        auth.assert_not_called()
        self.assertFalse(self.view_called)

    @patch(
        "qc_tool.frontend.dashboard.authentication.decorators.auth_worker"
    )
    def test_query_token_is_rejected_even_with_a_valid_header(self, auth):
        response = self.protected_view()(
            self.factory.post(
                "/pull_job?token=legacy-query-token",
                HTTP_AUTHORIZATION="WorkerToken valid-header-token",
            )
        )

        self.assertEqual(response.status_code, 401)
        auth.assert_not_called()
        self.assertFalse(self.view_called)

    @patch(
        "qc_tool.frontend.dashboard.authentication.decorators.auth_worker",
        return_value=False,
    )
    def test_invalid_authorization_token_is_rejected_before_view(self, auth):
        response = self.protected_view()(
            self.factory.post(
                "/pull_job",
                HTTP_AUTHORIZATION="WorkerToken invalid",
            )
        )

        self.assertEqual(response.status_code, 401)
        auth.assert_called_once_with("invalid")
        self.assertFalse(self.view_called)

    @patch(
        "qc_tool.frontend.dashboard.authentication.decorators.auth_worker",
        return_value=True,
    )
    def test_valid_authorization_token_allows_view(self, auth):
        response = self.protected_view()(
            self.factory.post(
                "/pull_job",
                HTTP_AUTHORIZATION="workertoken valid",
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"status": "ok"})
        self.assertEqual(response["Cache-Control"], "no-store, private")
        self.assertEqual(response["Vary"], "Authorization")
        auth.assert_called_once_with("valid")
        self.assertTrue(self.view_called)

    @patch(
        "qc_tool.frontend.dashboard.authentication.decorators.auth_worker"
    )
    def test_malformed_or_different_authorization_scheme_is_rejected(
        self,
        auth,
    ):
        for authorization in (
            "Bearer valid",
            WORKER_AUTH_SCHEME,
            "WorkerToken one two",
            "WorkerToken\tvalid",
            "WorkerToken " + ("x" * 300),
            "WorkerToken nön-ascii",
        ):
            with self.subTest(authorization=authorization):
                response = self.protected_view()(
                    self.factory.post(
                        "/pull_job",
                        HTTP_AUTHORIZATION=authorization,
                    )
                )
                self.assertEqual(response.status_code, 401)

        auth.assert_not_called()
        self.assertFalse(self.view_called)

    def test_worker_decorator_is_csrf_exempt(self):
        self.assertTrue(self.protected_view().csrf_exempt)


class PullJobAuthenticationIntegrationTests(SimpleTestCase):
    @patch("qc_tool.frontend.dashboard.views.models.pull_job")
    @patch(
        "qc_tool.frontend.dashboard.authentication.decorators.auth_worker",
        return_value=True,
    )
    def test_authenticated_get_cannot_claim_a_job(self, auth, pull_job):
        response = self.client.get(
            reverse("pull_job"),
            HTTP_AUTHORIZATION="WorkerToken valid",
        )

        self.assertEqual(response.status_code, 405)
        auth.assert_called_once_with("valid")
        pull_job.assert_not_called()

    @patch("qc_tool.frontend.dashboard.views.models.pull_job")
    @patch(
        "qc_tool.frontend.dashboard.authentication.decorators.auth_worker"
    )
    def test_missing_token_cannot_reach_pull_job_view(self, auth, pull_job):
        response = self.client.post(reverse("pull_job"))

        self.assertEqual(response.status_code, 401)
        auth.assert_not_called()
        pull_job.assert_not_called()

    @patch("qc_tool.frontend.dashboard.views.models.pull_job")
    @patch(
        "qc_tool.frontend.dashboard.authentication.decorators.auth_worker",
        return_value=False,
    )
    def test_invalid_token_cannot_reach_pull_job_view(self, auth, pull_job):
        response = self.client.post(
            reverse("pull_job"),
            HTTP_AUTHORIZATION="WorkerToken invalid",
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
    def test_valid_header_token_reaches_pull_job_view(self, auth, pull_job):
        csrf_enforcing_client = self.client_class(enforce_csrf_checks=True)
        response = csrf_enforcing_client.post(
            reverse("pull_job"),
            HTTP_AUTHORIZATION="WorkerToken valid",
        )

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, None)
        self.assertEqual(response["Cache-Control"], "no-store, private")
        auth.assert_called_once_with("valid")
        pull_job.assert_called_once()

    @patch("qc_tool.frontend.dashboard.views.models.pull_job")
    @patch(
        "qc_tool.frontend.dashboard.authentication.decorators.auth_worker"
    )
    def test_legacy_query_token_is_rejected(self, auth, pull_job):
        response = self.client.post(
            "{}?token=legacy-query-token".format(reverse("pull_job")),
        )

        self.assertEqual(response.status_code, 401)
        auth.assert_not_called()
        pull_job.assert_not_called()
