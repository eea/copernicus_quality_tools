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

    def static_source(self, relative_path):
        """Return one delivery asset so its browser contract can be audited."""

        source_path = finders.find(relative_path)
        self.assertIsNotNone(
            source_path,
            "Missing static asset: {}".format(relative_path),
        )
        return Path(source_path).read_text(encoding="utf-8")

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
                finders.find(
                    "dashboard/js/features/deliveries/rows/status.js"
                ),
                finders.find(
                    "dashboard/js/features/deliveries/rows/actions.js"
                ),
                finders.find(
                    "dashboard/js/features/deliveries/rows/overview.js"
                ),
                finders.find("dashboard/js/features/deliveries/table.js"),
                finders.find("dashboard/js/features/deliveries/dialogs.js"),
                finders.find("dashboard/js/features/deliveries/actions.js"),
                finders.find("dashboard/js/features/deliveries/index.js"),
            )
            if script_path is not None
        )

        self.assertIn("delivery-history-link", script)
        self.assertIn("delivery-job-link", script)
        self.assertIn("View QC result", script)
        self.assertIn("Review QC result", script)
        self.assertIn("View current QC job", script)
        self.assertIn("row.job_history_url", script)
        self.assertIn("row.job_result_url", script)
        self.assertNotIn("'/result/' +", script)

        # Untrusted filenames, product names, and AOI values must be assigned as
        # text or escaped by bootstrap-table, never interpolated into HTML.
        self.assertNotIn(".innerHTML", script)
        self.assertNotRegex(script, r"\.html\(\s*(?:row|value)\b")

    def test_table_has_no_dedicated_status_or_actions_column(self):
        """A row overview keeps state and controls next to their Delivery."""

        response = self.client.get(reverse("deliveries"))

        self.assertEqual(response.status_code, 200)
        document = response.content.decode(response.charset)
        header = re.search(
            r'<table\b[^>]*\bid="tbl-deliveries"[^>]*>.*?'
            r'<thead>(?P<body>.*?)</thead>',
            document,
            flags=re.IGNORECASE | re.DOTALL,
        )
        self.assertIsNotNone(header)

        data_headers = []
        for attributes, body in re.findall(
            r'<th\b(?P<attributes>[^>]*)>(?P<body>.*?)</th>',
            header.group("body"),
            flags=re.IGNORECASE | re.DOTALL,
        ):
            field = re.search(r'\bdata-field="([^"]+)"', attributes)
            if field:
                data_headers.append(
                    (
                        field.group(1),
                        " ".join(re.sub(r"<[^>]+>", " ", body).split()),
                        attributes,
                    )
                )

        self.assertEqual(
            [(field, label) for field, label, _attributes in data_headers],
            [("filename", "Delivery overview")],
        )
        self.assertIn(
            'data-formatter="deliveryOverviewFormatter"',
            data_headers[0][2],
        )
        self.assertNotIn('data-field="last_job_status"', header.group("body"))
        self.assertNotIn('data-field="product_description"', header.group("body"))
        self.assertNotIn("Status and actions", header.group("body"))
        self.assertNotIn('data-formatter="statusFormatter"', header.group("body"))

    def test_row_overview_groups_actions_and_keeps_destructive_action_last(self):
        """Row controls have context, native semantics, and a predictable order."""

        scripts = "\n".join(
            self.static_source(path)
            for path in (
                "dashboard/js/features/deliveries/formatters.js",
                "dashboard/js/features/deliveries/rows/status.js",
                "dashboard/js/features/deliveries/rows/actions.js",
                "dashboard/js/features/deliveries/rows/overview.js",
            )
        )

        self.assertIn("function deliveryOverviewFormatter", scripts)
        self.assertIn('"role": "group"', scripts)
        self.assertIn('"aria-label": "Actions for " + filename', scripts)
        self.assertIn("delivery-row-actions--destructive", scripts)
        self.assertIn('type: "button"', scripts)
        self.assertIn("row.delivery_status", scripts)
        self.assertIn("row.job_history_url", scripts)
        self.assertIn("row.job_result_url", scripts)
        self.assertIn("row.product_description", scripts)
        self.assertIn("row.product_ident", scripts)
        self.assertIn("row.aoi_code", scripts)
        self.assertIn("config.productDetailUrlTemplate", scripts)
        self.assertIn(
            "encodeURIComponent(String(row.product_ident))",
            scripts,
        )
        self.assertIn("text: status.label", scripts)
        self.assertIn("text: status.detail", scripts)

        action_plan = re.search(
            r"function plan\(row\)\s*\{(?P<body>.*?)"
            r"\n\s*function populate",
            scripts,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(action_plan)
        ordered_actions = ("submit", "result", "run", "delete")
        action_positions = [
            action_plan.group("body").index(
                'actions.push("{}")'.format(action)
            )
            for action in ordered_actions
        ]
        self.assertEqual(
            action_positions,
            sorted(action_positions),
            "The lifecycle plan must keep the next step first and delete last.",
        )
        self.assertNotIn("function statusFormatter", scripts)
        self.assertNotIn("function productFormatter", scripts)
        self.assertNotIn("window.statusFormatter", scripts)
        self.assertNotIn("window.statusCellStyle", scripts)
        self.assertNotIn("window.productFormatter", scripts)

    def test_table_interactions_remain_keyboard_accessible(self):
        script = self.static_source("dashboard/js/features/deliveries/table.js")

        self.assertIn('role: "button"', script)
        self.assertIn('tabindex: "0"', script)
        self.assertIn('event.key === "Enter"', script)
        self.assertIn('event.key === " "', script)
        self.assertIn('role: "region"', script)
        self.assertIn('"aria-labelledby": "deliveries-table-title"', script)
        self.assertIn('"aria-busy"', script)

    def test_overview_grid_collapses_without_the_legacy_wide_table(self):
        """Small screens get one readable summary flow instead of a wide table."""

        table_styles = "\n".join(
            self.static_source(path)
            for path in (
                "dashboard/css/features/deliveries/table.css",
                "dashboard/css/features/deliveries/rows/overview.css",
                "dashboard/css/features/deliveries/rows/status.css",
                "dashboard/css/features/deliveries/rows/actions.css",
            )
        )
        responsive_styles = self.static_source(
            "dashboard/css/features/deliveries/responsive.css"
        )

        self.assertNotRegex(table_styles, r"min-width\s*:\s*960px")
        self.assertRegex(
            table_styles,
            r"\.delivery-overview\s*\{[^}]*\bdisplay\s*:\s*grid\b",
        )
        self.assertRegex(
            responsive_styles,
            r"@media\s*\(max-width:\s*767px\)[\s\S]*"
            r"\.delivery-overview\s*\{[^}]*"
            r"grid-template-columns\s*:\s*1fr\b",
        )
        self.assertIn(".delivery-row-actions--destructive", table_styles)
