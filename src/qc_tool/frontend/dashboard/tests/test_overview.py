"""Truthful, access-scoped contracts for the workspace overview."""

from dataclasses import FrozenInstanceError
from datetime import timedelta
from html.parser import HTMLParser
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.contrib.staticfiles import finders
from django.db import connection
from django.templatetags.static import static
from django.test import TestCase
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from qc_tool.common import JOB_FAILED
from qc_tool.common import JOB_OK
from qc_tool.common import JOB_RUNNING
from qc_tool.frontend.accounts.authorization.permissions import (
    AccountPermission,
)
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.authorization import access_for
from qc_tool.frontend.accounts.services.role_permissions import (
    capability_content_type,
)
from qc_tool.frontend.accounts.services.products import (
    ProductCatalogUnavailable,
)
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.dashboard.services.overview import (
    build_workspace_overview,
)


class _MarkedContentParser(HTMLParser):
    """Collect text and links below elements carrying one semantic marker."""

    def __init__(self, *, attribute, value):
        super().__init__(convert_charrefs=True)
        self.attribute = attribute
        self.value = value
        self.depth = 0
        self.text = []
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if self.depth:
            self.depth += 1
        elif attributes.get(self.attribute) == self.value:
            self.depth = 1
        if self.depth and tag == "a" and attributes.get("href"):
            self.hrefs.append(attributes["href"])

    def handle_startendtag(self, tag, attrs):
        attributes = dict(attrs)
        if self.depth and tag == "a" and attributes.get("href"):
            self.hrefs.append(attributes["href"])

    def handle_endtag(self, _tag):
        if self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self.depth:
            self.text.append(data)

    @property
    def normalized_text(self):
        return " ".join("".join(self.text).split())


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class DashboardHomeContractTests(TestCase):
    """Keep dashboard values real, bounded, safe, and permission-aware."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="dashboard-user",
            password="test-password",
        )
        self.client.force_login(self.user)

    def permission(self, permission):
        return Permission.objects.get(
            content_type=capability_content_type(),
            codename=permission.value,
        )

    def remove_default_capabilities(self, *permissions):
        default_group = Group.objects.get(name=Role.DEFAULT.value)
        default_group.permissions.remove(
            *(self.permission(permission) for permission in permissions)
        )

    def create_delivery(
        self,
        *,
        filename,
        user=None,
        uploaded_at=None,
        submitted_at=None,
        product_ident=None,
        product_description=None,
        is_deleted=False,
    ):
        return Delivery.objects.create(
            user=self.user if user is None else user,
            filename=filename,
            size_bytes=1024,
            date_uploaded=uploaded_at or timezone.now(),
            date_submitted=submitted_at,
            product_ident=product_ident,
            product_description=product_description,
            is_deleted=is_deleted,
        )

    def create_job(self, *, delivery, status, created_at, description="Product"):
        return Job.objects.create(
            delivery=delivery,
            date_created=created_at,
            job_status=status,
            product_ident=delivery.product_ident or "test-product",
            product_description=description,
        )

    def marked(self, response, attribute, value):
        parser = _MarkedContentParser(attribute=attribute, value=value)
        parser.feed(response.content.decode(response.charset))
        self.assertTrue(
            parser.normalized_text or parser.hrefs,
            "Missing non-empty [{}={!r}] dashboard element".format(
                attribute,
                value,
            ),
        )
        return parser

    @patch("qc_tool.frontend.dashboard.views.products.available_product_descriptions")
    def test_kpis_use_visible_deliveries_and_each_latest_qc_state(self, catalog):
        catalog.return_value = {
            "product-a": "Product A",
            "product-b": "Product B",
            "product-c": "Product C",
        }
        now = timezone.now()

        submitted = self.create_delivery(
            filename="submitted.zip",
            submitted_at=now,
            product_ident="product-a",
        )
        self.create_job(delivery=submitted, status=JOB_OK, created_at=now)

        ready = self.create_delivery(
            filename="ready.zip",
            product_ident="product-a",
        )
        self.create_job(
            delivery=ready,
            status=JOB_FAILED,
            created_at=now - timedelta(hours=2),
        )
        self.create_job(
            delivery=ready,
            status=JOB_OK,
            created_at=now - timedelta(hours=1),
        )

        failed = self.create_delivery(
            filename="failed.zip",
            product_ident="product-b",
        )
        self.create_job(delivery=failed, status=JOB_FAILED, created_at=now)

        running = self.create_delivery(
            filename="running.zip",
            product_ident="product-b",
        )
        self.create_job(delivery=running, status=JOB_RUNNING, created_at=now)

        self.create_delivery(filename="not-checked.zip")
        unknown = self.create_delivery(filename="unknown.zip")
        self.create_job(
            delivery=unknown,
            status="legacy-unknown-status",
            created_at=now,
        )

        deleted = self.create_delivery(
            filename="deleted.zip",
            is_deleted=True,
        )
        self.create_job(delivery=deleted, status=JOB_OK, created_at=now)
        other_user = get_user_model().objects.create_user(
            username="hidden-dashboard-user",
            password="test-password",
        )
        hidden = self.create_delivery(
            filename="hidden.zip",
            user=other_user,
            submitted_at=now,
        )
        self.create_job(delivery=hidden, status=JOB_OK, created_at=now)
        Delivery.objects.create(
            user=None,
            filename="legacy-orphan.zip",
            size_bytes=1024,
        )

        response = self.client.get(reverse("dashboard_home"))

        self.assertEqual(response.status_code, 200)
        dashboard = response.context["dashboard"]
        summary = dashboard.summary
        self.assertEqual(summary.total_deliveries, 6)
        self.assertEqual(summary.qc_passed, 2)
        self.assertEqual(summary.qc_in_progress, 1)
        self.assertEqual(summary.qc_failed, 1)
        self.assertEqual(summary.not_checked, 1)
        self.assertEqual(summary.unknown_status, 1)
        self.assertEqual(summary.submitted_deliveries, 1)
        self.assertEqual(summary.ready_to_submit, 1)
        self.assertEqual(summary.needs_attention, 3)

        expected_metrics = {
            "deliveries": 6,
            "passed": 2,
            "attention": 3,
            "submitted": 1,
            "products": 3,
            "ready": 1,
        }
        for metric, expected in expected_metrics.items():
            with self.subTest(metric=metric):
                self.assertIn(
                    str(expected),
                    self.marked(
                        response,
                        "data-dashboard-metric",
                        metric,
                    ).normalized_text,
                )

        coverage = {segment.key: segment.count for segment in dashboard.coverage}
        self.assertEqual(
            coverage,
            {
                "submitted": 1,
                "ready": 1,
                "in_progress": 1,
                "blocked": 3,
            },
        )
        self.assertEqual(sum(coverage.values()), summary.total_deliveries)
        document = response.content.decode(response.charset)
        self.assertNotIn("hidden.zip", document)
        self.assertNotIn("legacy-orphan.zip", document)

    @patch("qc_tool.frontend.dashboard.views.products.available_product_descriptions")
    def test_snapshot_is_immutable_and_bounded(self, catalog):
        catalog.return_value = {
            "product-{:02d}".format(index): "Product {:02d}".format(index)
            for index in range(8)
        }
        now = timezone.now()
        for index in range(8):
            delivery = self.create_delivery(
                filename="delivery-{:02d}.zip".format(index),
                uploaded_at=now + timedelta(minutes=index),
                product_ident="product-{:02d}".format(index),
            )
            self.create_job(
                delivery=delivery,
                status=JOB_FAILED,
                created_at=now + timedelta(minutes=index),
            )

        response = self.client.get(reverse("dashboard_home"))

        self.assertEqual(response.status_code, 200)
        dashboard = response.context["dashboard"]
        self.assertIsInstance(dashboard.coverage, tuple)
        self.assertIsInstance(dashboard.product_attention, tuple)
        self.assertIsInstance(dashboard.recent_activity, tuple)
        self.assertLessEqual(len(dashboard.product_attention), 5)
        self.assertLessEqual(len(dashboard.recent_activity), 5)
        with self.assertRaises(FrozenInstanceError):
            dashboard.summary.total_deliveries = 999

    @patch("qc_tool.frontend.dashboard.views.products.available_product_descriptions")
    def test_quick_actions_follow_effective_permissions(self, catalog):
        catalog.return_value = {"product-a": "Product A"}

        response = self.client.get(reverse("dashboard_home"))

        self.assertEqual(response.status_code, 200)
        expected_links = {
            "upload": reverse("file_upload"),
            "deliveries": reverse("deliveries"),
            "products": reverse("products"),
            "api": reverse("api_homepage"),
            "tokens": reverse("account_settings"),
        }
        for action, expected_url in expected_links.items():
            with self.subTest(action=action):
                marker = self.marked(
                    response,
                    "data-dashboard-action",
                    action,
                )
                self.assertTrue(
                    any(
                        urlsplit(href).path == urlsplit(expected_url).path
                        for href in marker.hrefs
                    ),
                    "Dashboard action {!r} does not link to {}: {}".format(
                        action,
                        expected_url,
                        marker.hrefs,
                    ),
                )

        self.remove_default_capabilities(
            AccountPermission.UPLOAD_DELIVERY,
            AccountPermission.MANAGE_API_CREDENTIAL,
        )
        restricted_response = self.client.get(reverse("dashboard_home"))
        restricted_document = restricted_response.content.decode(
            restricted_response.charset
        )

        self.assertEqual(restricted_response.status_code, 200)
        self.assertNotIn('data-dashboard-action="upload"', restricted_document)
        self.assertNotIn('data-dashboard-action="tokens"', restricted_document)
        for action in ("deliveries", "products", "api"):
            with self.subTest(action=action):
                self.marked(
                    restricted_response,
                    "data-dashboard-action",
                    action,
                )

    @override_settings(SUBMISSION_ENABLED=True)
    @patch("qc_tool.frontend.dashboard.views.products.available_product_descriptions")
    def test_attention_calls_to_action_follow_effective_permissions(
        self,
        catalog,
    ):
        catalog.return_value = {"product-a": "Product A"}
        ready = self.create_delivery(
            filename="ready-for-submission.zip",
            product_ident="product-a",
        )
        self.create_job(
            delivery=ready,
            status=JOB_OK,
            created_at=timezone.now(),
        )
        self.create_delivery(filename="needs-qc.zip")

        permitted = self.client.get(reverse("dashboard_home"))

        self.assertEqual(permitted.status_code, 200)
        self.assertContains(permitted, "Passed QC and not submitted")
        self.assertContains(permitted, "1 passed QC and not submitted")
        self.assertContains(permitted, "Start QC")

        self.remove_default_capabilities(
            AccountPermission.RUN_QC,
            AccountPermission.SUBMIT_DELIVERY,
        )
        restricted = self.client.get(reverse("dashboard_home"))

        self.assertEqual(restricted.status_code, 200)
        # The KPI remains factual, but unauthorized calls to action disappear.
        self.assertContains(restricted, "Passed QC and not submitted")
        self.assertNotContains(restricted, "1 passed QC and not submitted")
        self.assertNotContains(restricted, "Start QC")
        self.assertNotContains(restricted, ">Submit <")

    @patch(
        "qc_tool.frontend.dashboard.views.overview.get_announcement_message"
    )
    @patch("qc_tool.frontend.dashboard.views.products.available_product_descriptions")
    def test_untrusted_dashboard_text_is_escaped(self, catalog, announcement):
        unsafe_filename = '<script>alert("delivery")</script>.zip'
        unsafe_product = '<svg onload="alert(2)">'
        unsafe_announcement = '<a href="javascript:alert(3)">notice</a>'
        catalog.return_value = {unsafe_product: unsafe_product}
        announcement.return_value = unsafe_announcement
        delivery = self.create_delivery(
            filename=unsafe_filename,
            product_ident=unsafe_product,
            product_description=unsafe_product,
        )
        self.create_job(
            delivery=delivery,
            status=JOB_FAILED,
            created_at=timezone.now(),
            description=unsafe_product,
        )

        response = self.client.get(reverse("dashboard_home"))

        self.assertEqual(response.status_code, 200)
        document = response.content.decode(response.charset)
        for unsafe_value in (
            unsafe_filename,
            unsafe_product,
            unsafe_announcement,
        ):
            with self.subTest(unsafe_value=unsafe_value):
                self.assertNotIn(unsafe_value, document)
                self.assertIn(escape(unsafe_value), document)

    @patch("qc_tool.frontend.dashboard.views.products.available_product_descriptions")
    def test_dashboard_does_not_claim_unsupported_aoi_or_trend_data(self, catalog):
        catalog.return_value = {"product-a": "Product A"}

        response = self.client.get(reverse("dashboard_home"))

        self.assertEqual(response.status_code, 200)
        document = response.content.decode(response.charset).casefold()
        for unsupported_claim in (
            "expected aois",
            "remaining aois",
            "this week",
            "expires in",
        ):
            with self.subTest(unsupported_claim=unsupported_claim):
                self.assertNotIn(unsupported_claim, document)

    @patch("qc_tool.frontend.dashboard.views.products.available_product_descriptions")
    def test_page_has_accessible_landmarks_and_truthful_empty_states(self, catalog):
        catalog.return_value = {}

        response = self.client.get(reverse("dashboard_home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<h1>Dashboard</h1>", html=True)
        self.assertContains(response, "Overview of your QC Tool workspace.")
        for heading_id, label in (
            ("dashboard-kpi-title", "Workspace overview"),
            ("dashboard-lifecycle-title", "Delivery submission status"),
            ("dashboard-attention-title", "Needs attention"),
            ("dashboard-products-attention-title", "Products with QC issues"),
            ("dashboard-activity-title", "Recent delivery activity"),
            ("dashboard-quick-actions-title", "Quick actions"),
        ):
            with self.subTest(heading_id=heading_id):
                self.assertContains(response, 'id="{}"'.format(heading_id))
                self.assertContains(response, label)
        self.assertContains(response, "No deliveries yet")
        self.assertContains(response, "No product issues to show")
        self.assertContains(
            response,
            '<nav aria-label="Dashboard quick actions">',
        )
        stylesheets = (
            "dashboard/css/features/overview/layout.css",
            "dashboard/css/features/overview/lifecycle.css",
            "dashboard/css/features/overview/attention.css",
            "dashboard/css/features/overview/activity.css",
            "dashboard/css/features/overview/responsive.css",
        )
        for stylesheet in stylesheets:
            with self.subTest(stylesheet=stylesheet):
                self.assertIsNotNone(finders.find(stylesheet))
                self.assertContains(response, static(stylesheet), count=1)

    @patch(
        "qc_tool.frontend.dashboard.views.products.available_product_descriptions",
        side_effect=ProductCatalogUnavailable("catalog unavailable"),
    )
    def test_catalog_failure_is_unavailable_instead_of_a_fake_zero(self, _catalog):
        response = self.client.get(reverse("dashboard_home"))

        self.assertEqual(response.status_code, 200)
        product_metric = self.marked(
            response,
            "data-dashboard-metric",
            "products",
        ).normalized_text
        self.assertIn("Available products", product_metric)
        self.assertIn("Unavailable", product_metric)
        self.assertNotRegex(product_metric, r"\b0\b")
        self.assertContains(response, "Product catalog unavailable")

    def test_service_queries_and_presentation_collections_are_bounded(self):
        now = timezone.now()
        for index in range(30):
            delivery = self.create_delivery(
                filename="bounded-{:02d}.zip".format(index),
                uploaded_at=now + timedelta(minutes=index),
                product_ident="bounded-product-{:02d}".format(index),
            )
            self.create_job(
                delivery=delivery,
                status=JOB_FAILED,
                created_at=now + timedelta(minutes=index),
            )
        account_access = access_for(self.user)

        with CaptureQueriesContext(connection) as queries:
            dashboard = build_workspace_overview(account_access)

        self.assertLessEqual(len(queries), 5)
        self.assertEqual(dashboard.summary.total_deliveries, 30)
        self.assertLessEqual(len(dashboard.product_attention), 5)
        self.assertLessEqual(len(dashboard.recent_activity), 5)

    def test_service_rejects_limits_that_could_create_unbounded_queries(self):
        account_access = access_for(self.user)

        for invalid_limit in (True, 0, -1, 21, "5", None):
            with self.subTest(invalid_limit=invalid_limit):
                with self.assertRaises(ValueError):
                    build_workspace_overview(
                        account_access,
                        recent_limit=invalid_limit,
                    )
                with self.assertRaises(ValueError):
                    build_workspace_overview(
                        account_access,
                        product_limit=invalid_limit,
                    )

    def test_coverage_is_disjoint_when_submitted_qc_is_still_running(self):
        now = timezone.now()
        submitted = self.create_delivery(
            filename="submitted-running.zip",
            submitted_at=now,
        )
        self.create_job(
            delivery=submitted,
            status=JOB_RUNNING,
            created_at=now,
        )
        unsubmitted = self.create_delivery(filename="running.zip")
        self.create_job(
            delivery=unsubmitted,
            status=JOB_RUNNING,
            created_at=now,
        )

        dashboard = build_workspace_overview(access_for(self.user))

        coverage = {segment.key: segment.count for segment in dashboard.coverage}
        self.assertEqual(
            coverage,
            {
                "submitted": 1,
                "ready": 0,
                "in_progress": 1,
                "blocked": 0,
            },
        )
        self.assertEqual(
            sum(coverage.values()),
            dashboard.summary.total_deliveries,
        )

    def test_product_attention_groups_case_variant_identifiers(self):
        now = timezone.now()
        for identifier in ("CLMS_UA_CHANGE", "clms_ua_change"):
            delivery = self.create_delivery(
                filename="{}.zip".format(identifier),
                product_ident=identifier,
                product_description="Urban Atlas Change",
            )
            self.create_job(
                delivery=delivery,
                status=JOB_FAILED,
                created_at=now,
            )

        dashboard = build_workspace_overview(access_for(self.user))

        self.assertEqual(len(dashboard.product_attention), 1)
        product = dashboard.product_attention[0]
        self.assertEqual(product.identifier.casefold(), "clms_ua_change")
        self.assertEqual(product.total_deliveries, 2)
        self.assertEqual(product.needs_attention, 2)

    def test_unfinished_terminal_job_does_not_claim_a_qc_outcome_time(self):
        now = timezone.now()
        delivery = self.create_delivery(
            filename="unfinished-terminal.zip",
            uploaded_at=now - timedelta(days=1),
        )
        job = self.create_job(
            delivery=delivery,
            status=JOB_OK,
            created_at=now,
        )
        self.assertIsNone(job.date_finished)

        dashboard = build_workspace_overview(access_for(self.user))

        qc_items = [
            item for item in dashboard.recent_activity if item.kind == "qc"
        ]
        self.assertFalse(
            any("passed QC" in item.title for item in qc_items),
            "A terminal status without date_finished is not a dated QC outcome.",
        )
