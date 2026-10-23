"""Browsing stays useful during maintenance without hidden database writes."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.db import connection
from django.http import HttpResponse, StreamingHttpResponse
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import include, path, reverse

from qc_tool.common import JOB_WAITING
from qc_tool.database.transfers import service as transfer_service
from qc_tool.frontend.accounts.services.api_tokens import issue_personal_access_token
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.dashboard.models import Delivery, Job
from qc_tool.frontend.dashboard.services import maintenance
from qc_tool.frontend.dashboard.services.maintenance.reads import (
    MaintenanceWriteBlocked, _read_query, read_only_database_access,
)


def unintended_get_write(request):
    get_user_model().objects.filter(pk=request.user.pk).update(first_name="unsafe")
    return HttpResponse("should not finish")


def read_stream(request):
    def rows():
        yield str(Job.objects.count()).encode()
    return StreamingHttpResponse(rows())


urlpatterns = [
    path("_maintenance/write-get/", unintended_get_write, name="unintended_get_write"),
    path("_maintenance/read-stream/", read_stream, name="maintenance_read_stream"),
    path("", include("qc_tool.frontend.urls")),
]


@override_settings(ROOT_URLCONF=__name__, MAINTENANCE_MODE=False)
class MaintenanceBrowsingTests(TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(override_settings(QC_TOOL_MAINTENANCE_DIR=Path(directory) / "maintenance"))
        self.user = get_user_model().objects.create_superuser(username="maintenance-browse", password="test-password")
        self.client.force_login(self.user)
        self.delivery = Delivery.objects.create(user=self.user, filename="browse.zip", size_bytes=1)
        self.token = issue_personal_access_token(self.user, "Read API")
        maintenance.enable("root", 0)

    def without_writes(self, callback):
        with CaptureQueriesContext(connection) as queries:
            response = callback()
        mutations = [query["sql"] for query in queries if query["sql"].lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER ", "DROP "))]
        self.assertEqual(mutations, [])
        return response

    @override_settings(SESSION_SAVE_EVERY_REQUEST=True)
    def test_existing_sessions_browse_workspace_and_admin_without_mutations(self):
        before = list(Session.objects.values())
        for phase in ("stopping", "ready"):
            if phase == "ready":
                maintenance.advance(1)
            for name in ("dashboard_home", "deliveries", "products", "boundaries", "account_settings", "admin:index", "login"):
                with self.subTest(phase=phase, route=name):
                    response = self.without_writes(lambda: self.client.get(reverse(name)))
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response["X-QC-Maintenance"], "on")
        self.assertEqual(before, list(Session.objects.values()))

    def test_reads_keep_object_ownership_permissions(self):
        other = get_user_model().objects.create_user(username="maintenance-other")
        UserProductGrant.objects.create(user=other, product_ident="maintenance-product")
        foreign = Delivery.objects.create(user=other, filename="private.zip", size_bytes=1)
        self.client.force_login(other)
        response = self.without_writes(lambda: self.client.get(reverse("job_history", args=(self.delivery.pk,))))
        self.assertIn(response.status_code, (403, 404))
        self.assertEqual(self.client.get(reverse("job_history", args=(foreign.pk,))).status_code, 200)

    def test_api_browsing_does_not_record_token_use(self):
        response = self.without_writes(lambda: self.client.get(reverse("api_delivery_list"), HTTP_AUTHORIZATION="Bearer " + self.token.raw_token))
        self.assertEqual(response.status_code, 200)
        self.token.token.refresh_from_db()
        self.assertIsNone(self.token.token.last_used_at)
        self.assertEqual(self.client.get(reverse("api_delivery_list")).status_code, 401)

    def test_safe_post_export_retains_csrf_and_permissions(self):
        payload = {"format": "json", "filename": "browse", "columns": [{"field": "name", "label": "Name"}], "rows": [{"name": "Existing data"}]}
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        url = reverse("table_export")
        self.assertEqual(client.post(url, payload, content_type="application/json").status_code, 403)
        client.get(reverse("deliveries"))
        token = client.cookies["csrftoken"].value
        response = self.without_writes(lambda: client.post(url, payload, content_type="application/json", HTTP_X_CSRFTOKEN=token))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Existing data", b"".join(response.streaming_content))
        # Django's test-client iterator closes the response on exhaustion.
        self.assertTrue(response.closed)

    def test_get_upload_probe_and_every_mutating_method_stay_blocked(self):
        for method, url in (("get", reverse("resumable_upload")), ("post", reverse("create_job")), ("post", reverse("product_upload")), ("post", reverse("logout")), ("post", reverse("account_settings")), ("post", reverse("api_token_create")), ("post", reverse("admin:index")), ("delete", "/_maintenance/read-stream/")):
            with self.subTest(method=method, url=url):
                self.assertEqual(self.without_writes(lambda: getattr(self.client, method)(url)).status_code, 503)

    def test_read_request_does_not_block_writer_readiness_or_leak_query_guard(self):
        job = Job.objects.create(delivery=self.delivery, job_status=JOB_WAITING, product_ident="test", product_description="Test")
        response = self.client.get(reverse("maintenance_read_stream"))
        try:
            self.assertEqual(response.status_code, 200)
            # The stream has not started. This same thread may still execute
            # an operator action; no read query wrapper may leak across calls.
            self.assertEqual(maintenance.advance(1)["phase"], "ready")
            job.refresh_from_db()
            self.assertNotEqual(job.job_status, JOB_WAITING)
            self.assertTrue(b"".join(response.streaming_content))
        finally:
            if not response.closed:
                response.close()

    def test_unexpected_get_write_is_rejected_before_persistence(self):
        response = self.client.get(reverse("unintended_get_write"))
        self.assertEqual(response.status_code, 503)
        self.user.refresh_from_db()
        self.assertNotEqual(self.user.first_name, "unsafe")

    def test_schema_preflight_remains_read_only_after_maintenance_is_ready(self):
        self.assertEqual(maintenance.advance(1)["phase"], "ready")
        with read_only_database_access():
            readiness = self.without_writes(transfer_service.schema_readiness)
        self.assertTrue(readiness["ready"], readiness["message"])

    def test_query_guard_blocks_mutating_ctes_and_multiple_statements(self):
        execute = Mock()
        for sql in ("UPDATE auth_user SET first_name='bad'", "WITH changed AS (DELETE FROM execution_job RETURNING *) SELECT * FROM changed", "SELECT 1; DELETE FROM execution_job", "BEGIN ATOMIC UPDATE auth_user SET first_name='bad'; END", "SELECT * INTO copied_users FROM auth_user"):
            with self.subTest(sql=sql), self.assertRaises(MaintenanceWriteBlocked):
                _read_query(execute, sql, None, False, {})
        execute.assert_not_called()


class MaintenanceSQLitePragmaTests(SimpleTestCase):
    def test_metadata_pragmas_are_allowed_only_on_sqlite(self):
        context = {"connection": SimpleNamespace(vendor="sqlite")}
        for name in ("table_info", "table_xinfo", "index_list", "index_info", "foreign_key_list"):
            for argument in ('"auth_user"', '"quoted""identifier"'):
                with self.subTest(name=name, argument=argument):
                    execute = Mock()
                    _read_query(execute, f"PRAGMA {name}({argument})", None, False, context)
                    execute.assert_called_once()
        with self.assertRaises(MaintenanceWriteBlocked):
            _read_query(Mock(), 'PRAGMA table_info("auth_user")', None, False,
                        {"connection": SimpleNamespace(vendor="postgresql")})

    def test_mutating_and_unrecognized_pragmas_are_refused(self):
        context = {"connection": SimpleNamespace(vendor="sqlite")}
        execute = Mock()
        for sql in (
            "PRAGMA foreign_keys = OFF", "PRAGMA writable_schema(1)",
            "PRAGMA journal_mode(WAL)", "PRAGMA user_version = 2",
            'PRAGMA table_info("auth_user"); DELETE FROM auth_user',
            'PRAGMA table_info("auth_user") = 1', 'PRAGMA optimize',
            'PRAGMA wal_checkpoint(TRUNCATE)',
        ):
            with self.subTest(sql=sql), self.assertRaises(MaintenanceWriteBlocked):
                _read_query(execute, sql, None, False, context)
        execute.assert_not_called()
