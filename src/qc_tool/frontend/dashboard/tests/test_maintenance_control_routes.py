"""Maintenance controls continue working behind deployment path prefixes."""

import asyncio
from unittest.mock import Mock
from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory
from django.test import SimpleTestCase
from django.test import override_settings
from django.urls import path

from qc_tool.frontend.dashboard.access.maintenance import is_maintenance_control_request
from qc_tool.frontend.dashboard.middleware import MaintenanceModeMiddleware
from qc_tool.frontend.dashboard.middleware import MaintenanceSessionMiddleware


def control_view(request):
    return HttpResponse("control")


urlpatterns = [
    path("operations/pause/", control_view, name="admin_maintenance"),
    path("internal/pause/", control_view, name="worker_maintenance"),
    path("admin/login/", control_view, name="ordinary_admin_login"),
]


@override_settings(ROOT_URLCONF=__name__)
class MaintenanceControlRouteTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_prefixed_and_relocated_controls_use_named_route_ownership(self):
        for path_info in ("/operations/pause/", "/internal/pause/"):
            with self.subTest(path_info=path_info):
                request = self.factory.get(path_info, SCRIPT_NAME="/qc-tool")
                self.assertEqual(request.path, "/qc-tool" + path_info)
                self.assertTrue(is_maintenance_control_request(request))

    def test_request_specific_urlconf_is_respected(self):
        request = self.factory.get("/operations/pause/")
        request.urlconf = __name__
        with override_settings(ROOT_URLCONF="qc_tool.frontend.urls"):
            self.assertTrue(is_maintenance_control_request(request))

    def test_admin_login_and_unknown_routes_cannot_bypass_admission(self):
        for path_info in ("/admin/login/", "/missing/"):
            with self.subTest(path_info=path_info):
                self.assertFalse(is_maintenance_control_request(self.factory.get(path_info)))

    def test_prefixed_control_bypasses_application_admission(self):
        handler = Mock(return_value=HttpResponse("control"))
        request = self.factory.get("/operations/pause/", SCRIPT_NAME="/qc-tool")
        with patch("qc_tool.frontend.dashboard.middleware.application_activity", side_effect=AssertionError("ordinary admission must not run")):
            response = MaintenanceModeMiddleware(handler)(request)

        self.assertEqual(response.content, b"control")
        handler.assert_called_once_with(request)

    def test_prefixed_liveness_does_not_read_state(self):
        request = self.factory.get("/health", SCRIPT_NAME="/qc-tool")
        with patch("qc_tool.frontend.dashboard.middleware.application_activity", side_effect=AssertionError("ordinary admission must not run")):
            response = MaintenanceModeMiddleware(Mock())(request)

        self.assertEqual(response.status_code, 200)

    def test_prefixed_controls_receive_read_only_sessions(self):
        request = self.factory.get("/operations/pause/", SCRIPT_NAME="/qc-tool")
        middleware = MaintenanceSessionMiddleware(lambda request: HttpResponse("control"))
        middleware.process_request(request)

        self.assertTrue(request._maintenance_readonly_session)
        request.session.save()
        request.session.create()
        request.session.delete("unused-key")
        asyncio.run(request.session.asave())
        asyncio.run(request.session.acreate())
        asyncio.run(request.session.adelete("unused-key"))
        response = middleware.process_response(request, HttpResponse("control"))
        self.assertEqual(response["Cache-Control"], "no-store, private")
