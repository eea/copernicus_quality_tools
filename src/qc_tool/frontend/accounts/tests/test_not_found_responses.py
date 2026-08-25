"""Integration tests for safe, representation-aware 404 responses."""

import json
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.http import Http404
from django.test import RequestFactory
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from qc_tool.frontend.accounts.authentication.api_keys import (
    issue_or_rotate_api_key,
)
from qc_tool.frontend.accounts.authentication.decorators import api_key_required
from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.dashboard.authentication import worker_token_required


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class NotFoundResponseTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="not-found-user",
        )

    def test_unknown_url_uses_generic_anonymous_recovery_page(self):
        marker = "private-lookup-detail-should-not-appear"

        response = self.client.get("/missing/{}/".format(marker))

        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "accounts/errors/404.html")
        self.assertContains(
            response,
            "We couldn’t find that page",
            status_code=404,
        )
        self.assertContains(
            response,
            'class="btn btn-primary error-primary-action"',
            status_code=404,
        )
        self.assertContains(response, "#home", status_code=404)
        self.assertContains(response, "Go to homepage", status_code=404)
        self.assertNotContains(response, "Go to deliveries", status_code=404)
        self.assertIn(
            b'<main id="main-content" class="site-main error-page"',
            response.content,
        )
        self.assertEqual(response.content.count(b"<main"), 1)
        self.assertNotIn(b"container-fluid main error-page", response.content)
        self.assertNotContains(response, marker, status_code=404)
        self.assertEqual(
            response["X-Robots-Tag"],
            "noindex, nofollow, noarchive",
        )
        self.assertContains(
            response,
            'content="noindex, nofollow, noarchive"',
            status_code=404,
        )
        self.assertIn("private", response["Cache-Control"])
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("Cookie", response["Vary"])

    def test_unknown_head_request_keeps_404_without_a_response_body(self):
        response = self.client.head("/missing-head-route/")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"")

    def test_authenticated_missing_page_offers_homepage_recovery(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("show_result", args=(uuid4(),)),
        )

        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "accounts/errors/404.html")
        self.assertContains(response, "Go to homepage", status_code=404)
        self.assertContains(response, reverse("deliveries"), status_code=404)

    def test_private_page_authentication_runs_before_object_lookup(self):
        response = self.client.get(
            reverse("show_result", args=(uuid4(),)),
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("login")))

    def test_session_data_route_returns_generic_json_not_html(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("job_report_json", args=(uuid4(),)),
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {
                "status": "error",
                "code": "not_found",
                "message": "The requested resource was not found.",
            },
        )
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("Cookie", response["Vary"])

    def test_session_data_authentication_precedes_missing_resource(self):
        response = self.client.get(
            reverse("job_report_json", args=(uuid4(),)),
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "authentication_required")

    def test_api_wrapper_returns_json_and_authorization_cache_controls(self):
        raw_key = issue_or_rotate_api_key(self.user)

        @api_key_required(permission=AccountPermission.VIEW_DELIVERIES)
        def missing_resource(_request):
            raise Http404("sensitive API lookup detail")

        request = RequestFactory().get(
            "/test-api-resource/",
            HTTP_AUTHORIZATION="Bearer {}".format(raw_key),
        )
        response = missing_resource(request)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(json.loads(response.content)["code"], "not_found")
        self.assertNotIn(b"sensitive API lookup detail", response.content)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("Authorization", response["Vary"])

    @patch(
        "qc_tool.frontend.dashboard.authentication.decorators.auth_worker",
        return_value=True,
    )
    def test_worker_wrapper_keeps_status_only_not_found(self, _auth_worker):
        @worker_token_required
        def missing_resource(_request):
            raise Http404("sensitive worker lookup detail")

        request = RequestFactory().post(
            "/test-worker-resource/",
            HTTP_AUTHORIZATION="WorkerToken valid-worker-token",
        )
        response = missing_resource(request)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"")
        self.assertIn("Authorization", response["Vary"])

    def test_explicit_protocol_404_is_not_rewritten(self):
        self.client.force_login(self.user)
        parameters = {
            "resumableIdentifier": "missing-chunk",
            "resumableFilename": "delivery.zip",
            "resumableChunkNumber": "1",
            "resumableChunkSize": "1",
            "resumableCurrentChunkSize": "1",
            "resumableTotalChunks": "1",
            "resumableTotalSize": "1",
        }

        with TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                response = self.client.get(
                    reverse("resumable_upload"),
                    parameters,
                )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"")


class DebugNotFoundResponseTests(TestCase):
    @override_settings(DEBUG=True, MAINTENANCE_MODE=False)
    def test_development_keeps_djangos_diagnostic_404(self):
        response = self.client.get("/missing-development-route/")

        self.assertEqual(response.status_code, 404)
        self.assertTemplateNotUsed(response, "accounts/errors/404.html")
