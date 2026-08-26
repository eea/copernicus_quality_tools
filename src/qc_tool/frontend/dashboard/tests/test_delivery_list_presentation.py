"""Accessible presentation contracts for the delivery list workspace.

These tests intentionally describe stable user-facing semantics rather than
the page's visual implementation.  They allow the layout and CSS to evolve
without losing keyboard-accessible status filters or the distinction between
a delivery and its latest QC job.
"""

import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse


STATUS_FILTERS = (
    "all",
    "not_validated",
    "running",
    "passed",
    "failed",
    "submitted",
)


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class DeliveryListPresentationTests(TestCase):
    """Keep delivery filtering and job navigation explicit and accessible."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="delivery-list-presentation-user",
            password="test-password",
        )
        self.client.force_login(self.user)

    def test_status_filters_are_buttons_with_a_single_pressed_state(self):
        response = self.client.get(reverse("deliveries"))

        self.assertEqual(response.status_code, 200)
        document = response.content.decode(response.charset)
        navigation = re.search(
            r'<nav\b(?=[^>]*\bid="delivery-status-filters")'
            r'(?=[^>]*\baria-label="Filter deliveries by status")[^>]*>'
            r'(?P<body>.*?)</nav>',
            document,
            flags=re.IGNORECASE | re.DOTALL,
        )
        self.assertIsNotNone(
            navigation,
            "Delivery status controls need a labelled navigation landmark.",
        )

        buttons = re.findall(
            r'<button\b(?P<attributes>[^>]*)>(?P<body>.*?)</button>',
            navigation.group("body"),
            flags=re.IGNORECASE | re.DOTALL,
        )
        controls = {}
        for attributes, body in buttons:
            status = re.search(
                r'\bdata-delivery-status="([^"]+)"',
                attributes,
                flags=re.IGNORECASE,
            )
            if status:
                controls[status.group(1)] = (attributes, body)

        self.assertEqual(tuple(controls), STATUS_FILTERS)
        for status, (attributes, body) in controls.items():
            with self.subTest(status=status):
                self.assertRegex(attributes, r'\btype="button"')
                self.assertRegex(attributes, r'\baria-pressed="(?:true|false)"')
                self.assertIn(
                    'data-delivery-status-count="{}"'.format(status),
                    body,
                )

        pressed = [
            status
            for status, (attributes, _body) in controls.items()
            if 'aria-pressed="true"' in attributes
        ]
        self.assertEqual(pressed, ["all"])

    def test_search_product_and_aoi_controls_have_explicit_labels(self):
        response = self.client.get(reverse("deliveries"))

        self.assertEqual(response.status_code, 200)
        document = response.content.decode(response.charset)
        self.assertIn(
            '<section class="delivery-filter-panel" '
            'aria-labelledby="delivery-filter-title">',
            document,
        )
        for control_id, label in (
            ("delivery-filter-search", "Search deliveries"),
            ("delivery-filter-product", "Product"),
            ("delivery-filter-aoi", "AOI"),
        ):
            with self.subTest(control_id=control_id):
                self.assertIn(
                    '<label for="{}">{}</label>'.format(control_id, label),
                    document,
                )
                self.assertRegex(
                    document,
                    r'<(?:input|select)\b[^>]*\bid="{}"'.format(
                        re.escape(control_id)
                    ),
                )
        self.assertIn('id="btn-clear-filters"', document)
        self.assertIn(
            'id="btn-refresh-deliveries"',
            document,
        )
        self.assertIn('aria-label="Refresh deliveries"', document)

    def test_delivery_and_latest_qc_job_are_separate_link_destinations(self):
        response = self.client.get(reverse("deliveries"))

        self.assertEqual(response.status_code, 200)
        document = response.content.decode(response.charset)
        self.assertIn('id="tbl-deliveries"', document)

        script = "\n".join(
            Path(script_path).read_text(encoding="utf-8")
            for script_path in (
                finders.find("dashboard/js/features/deliveries/formatters.js"),
                finders.find("dashboard/js/features/deliveries/table.js"),
                finders.find("dashboard/js/features/deliveries/dialogs.js"),
                finders.find("dashboard/js/features/deliveries/actions.js"),
                finders.find("dashboard/js/features/deliveries/index.js"),
            )
            if script_path is not None
        )

        self.assertIn("delivery-history-link", script)
        self.assertIn("delivery-job-link", script)
        self.assertIn("View latest QC job", script)
        self.assertIn("row.job_history_url", script)
        self.assertIn("row.job_result_url", script)
        self.assertNotIn("'/result/' +", script)

        # Untrusted filenames, product names, and AOI values must be assigned as
        # text or escaped by bootstrap-table, never interpolated into HTML.
        self.assertNotIn(".innerHTML", script)
        self.assertNotRegex(script, r"\.html\(\s*(?:row|value)\b")
