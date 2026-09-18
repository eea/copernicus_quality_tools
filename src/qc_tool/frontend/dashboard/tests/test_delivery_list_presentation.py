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


STATUS_FILTERS = ("action_required", "running", "in_review", "completed", "all")


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
            r'<nav\b(?=[^>]*\bid="delivery-workflow-tabs")'
            r'(?=[^>]*\baria-label="Delivery workflow")[^>]*>'
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
                r'\bdata-delivery-view="([^"]+)"',
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
                    'data-delivery-view-count="{}"'.format(status),
                    body,
                )

        pressed = [
            status
            for status, (attributes, _body) in controls.items()
            if 'aria-pressed="true"' in attributes
        ]
        self.assertEqual(pressed, ["action_required"])

    def test_search_product_and_aoi_controls_have_explicit_labels(self):
        response = self.client.get(reverse("deliveries"))

        self.assertEqual(response.status_code, 200)
        document = response.content.decode(response.charset)
        self.assertRegex(
            document,
            r'<div\b[^>]*id="delivery-table-toolbar"[^>]*data-table-filter-toolbar',
        )
        self.assertIn('role="search" aria-label="Search deliveries"', document)
        for control_id, label in (
            ("delivery-filter-search", "Search deliveries"),
            ("delivery-filter-product", "Product"),
            ("delivery-filter-aoi", "AOI"),
        ):
            with self.subTest(control_id=control_id):
                self.assertRegex(
                    document,
                    r'<label\b[^>]*for="{}"[^>]*>{}</label>'.format(control_id, label),
                )
                self.assertRegex(
                    document,
                    r'<(?:input|select)\b[^>]*\bid="{}"'.format(
                        re.escape(control_id)
                    ),
                )
        self.assertIn('id="btn-clear-filters"', document)

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
        self.assertIn('"class": "delivery-cell__filename"', script)
        self.assertIn('"class": "delivery-history-link__label"', script)
        self.assertIn('text: "QC history"', script)
        self.assertIn('formatters.icon("history")', script)
        self.assertNotIn("delivery-history-link__filename", script)
        self.assertIn("delivery-job-link", script)
        self.assertIn("View QC result", script)
        self.assertIn("Review QC result", script)
        self.assertIn("View QC progress", script)
        self.assertIn("row.job_history_url", script)
        self.assertIn("row.job_result_url", script)
        self.assertNotIn("'/result/' +", script)

        # Untrusted filenames, product names, and AOI values must be assigned as
        # text or escaped by bootstrap-table, never interpolated into HTML.
        self.assertNotIn(".innerHTML", script)
        self.assertNotRegex(script, r"\.html\(\s*(?:row|value)\b")

    def test_product_aoi_only_appears_after_successful_qc(self):
        """Do not imply that an unavailable or failed AOI was validated."""

        script = self.static_source(
            "dashboard/js/features/deliveries/rows/overview.js"
        )

        self.assertIn(
            'String(row.last_job_status || "").toLowerCase() === "ok"',
            script,
        )
        self.assertIn("row.aoi_code_submitted || row.aoi_code", script)
        self.assertIn('text: "AOI: " + aoiCode', script)
        self.assertNotIn("AOI not available", script)
        self.assertNotIn("delivery-aoi--empty", script)

    def test_workflow_navigation_keeps_history_secondary_and_actions_grouped(self):
        response = self.client.get(reverse("deliveries"))
        document = response.content.decode(response.charset)
        nav = re.search(r'<nav[^>]*id="delivery-workflow-tabs".*?</nav>', document, re.DOTALL).group(0)
        self.assertIn('data-delivery-view="all"', nav)
        self.assertRegex(nav, r'<li class="qc-section-tabs__end">\s*<button[^>]*data-delivery-view="all"')
        self.assertEqual(document.count('data-delivery-view="all"'), 1)
        self.assertEqual(
            [group["label"] for group in response.context["delivery_action_groups"]],
            ["Review changes", "Resolve QC issues", "Run QC", "Submit"],
        )
        self.assertContains(response, 'id="delivery-workflow-config"')
        self.assertContains(response, 'id="delivery-action-groups"')
        self.assertContains(response, 'qc-section-tabs__indicator')

    def test_table_has_clear_semantic_columns_with_optional_details(self):
        """Core workflow columns stay visible while details can be toggled."""

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
            [
                ("filename", "Delivery"),
                ("product_description", "Product"),
                ("date_uploaded", "Uploaded"),
                ("size_bytes", "Size"),
                ("type", "Source"),
                ("username", "Owner"),
                ("id", "ID"),
                ("last_job_status", "Status"),
                ("actions", "Next action"),
            ],
        )
        formatters = (
            "deliveryFormatter",
            "productFormatter",
            "uploadedFormatter",
            "sizeFormatter",
            "sourceFormatter",
            "ownerFormatter",
            "idFormatter",
            "statusFormatter",
            "actionsFormatter",
        )
        for data_header, formatter in zip(data_headers, formatters):
            with self.subTest(field=data_header[0]):
                self.assertIn(
                    'data-formatter="{}"'.format(formatter),
                    data_header[2],
                )

        by_field = {
            field: attributes
            for field, _label, attributes in data_headers
        }
        for field, attributes in by_field.items():
            with self.subTest(column_field=field):
                if field == "actions":
                    self.assertIn('data-switchable="false"', attributes)
                else:
                    self.assertNotIn('data-switchable="false"', attributes)
        for field in ("size_bytes", "type", "username", "id"):
            with self.subTest(hidden_field=field):
                self.assertIn('data-visible="false"', by_field[field])

    def test_table_uses_the_shared_columns_and_export_toolbar(self):
        """Data-table controls share one labelled, reusable UI contract."""

        response = self.client.get(reverse("deliveries"))

        self.assertEqual(response.status_code, 200)
        document = response.content.decode(response.charset)
        region = re.search(
            r'<div\b(?=[^>]*\bclass="[^"]*\bqc-data-table-region\b)[^>]*>',
            document,
            flags=re.IGNORECASE,
        )
        table = re.search(
            r'<table\b(?=[^>]*\bid="tbl-deliveries")'
            r'(?=[^>]*\bclass="[^"]*\bqc-data-table\b)[^>]*>',
            document,
            flags=re.IGNORECASE,
        )
        self.assertIsNotNone(region)
        self.assertIsNotNone(table)
        for asset_path in (
            "dashboard/css/ui/data-table.css",
            "dashboard/css/ui/table-toolbar.css",
            "dashboard/js/shared/table-filters.js",
            "dashboard/js/shared/table-exports.js",
            "dashboard/js/shared/data-table-ui.js",
        ):
            with self.subTest(asset_path=asset_path):
                self.assertIn(asset_path, document)
                self.assertIsNotNone(finders.find(asset_path))

        shared_script = self.static_source(
            "dashboard/js/shared/data-table-ui.js"
        )
        table_script = self.static_source(
            "dashboard/js/features/deliveries/table.js"
        )
        self.assertIn("window.QcDataTableUi", shared_script)
        for common_option in (
            "showColumns",
            "showButtonText",
            "showColumnsToggleAll",
            "minimumCountColumns",
            "exportMenu",
        ):
            with self.subTest(common_option=common_option):
                self.assertIn(common_option, shared_script)
        self.assertIn("QcDataTableUi", table_script)
        self.assertIn("dataTableUi.create", table_script)

    def test_generated_export_keeps_the_server_filtered_delivery_export(self):
        """Toolbar reuse must not reduce export to the current client page."""

        response = self.client.get(reverse("deliveries"))

        self.assertEqual(response.status_code, 200)
        document = response.content.decode(response.charset)
        scripts = "\n".join(
            self.static_source(path)
            for path in (
                "dashboard/js/features/deliveries/table.js",
                "dashboard/js/features/deliveries/actions.js",
            )
        )
        self.assertNotIn('id="btn-export"', document)
        self.assertNotIn("#btn-export", scripts)
        self.assertIn("QcDataTableUi", scripts)
        self.assertIn("config.exportUrl", scripts)
        self.assertIn("exportQuery", scripts)
        self.assertIn("server: {url: config.exportUrl, getQuery: exportQuery}", scripts)
        self.assertIn('id="qc-table-export-config"', document)
        for label in ("JSON", "CSV", "XLSX", "XML"):
            self.assertIn(f'"label": "{label}"', document)
        self.assertIn('data-export-field="delivery_status"', document)
        self.assertIn('data-exportable="false"', document)

    def test_cell_formatters_prioritize_next_step_and_keep_delete_last(self):
        """Row controls expose one next step and quieter supporting actions."""

        scripts = "\n".join(
            self.static_source(path)
            for path in (
                "dashboard/js/features/deliveries/formatters.js",
                "dashboard/js/features/deliveries/rows/status.js",
                "dashboard/js/features/deliveries/rows/actions.js",
                "dashboard/js/features/deliveries/rows/overview.js",
            )
        )

        for formatter in (
            "deliveryFormatter",
            "productFormatter",
            "uploadedFormatter",
            "sizeFormatter",
            "sourceFormatter",
            "ownerFormatter",
            "idFormatter",
            "statusFormatter",
            "actionsFormatter",
        ):
            self.assertIn("function {}".format(formatter), scripts)
        self.assertIn('"role": "group"', scripts)
        self.assertIn('"aria-label": "Actions for " + filename', scripts)
        self.assertIn("delivery-row-actions__primary", scripts)
        self.assertIn("delivery-row-actions__secondary", scripts)
        self.assertIn("delivery-row-actions__destructive", scripts)
        self.assertIn("delivery-row-action--danger", scripts)
        self.assertIn('action !== "delete" && !primaryAssigned', scripts)
        self.assertIn("primaryAssigned = true", scripts)
        self.assertIn("appendDelete($destructive, row, filename)", scripts)
        self.assertIn("delivery-row-actions-empty", scripts)
        self.assertIn("No action required", scripts)
        self.assertIn('type: "button"', scripts)
        self.assertIn("row.delivery_status", scripts)
        self.assertIn("row.job_history_url", scripts)
        self.assertIn("row.job_result_url", scripts)
        self.assertIn("row.product_description", scripts)
        self.assertIn("row.product_url", scripts)
        self.assertIn("row.aoi_code", scripts)
        self.assertIn("row.product_url", scripts)
        self.assertIn("row.product_display_name", scripts)
        self.assertIn("text: status.label", scripts)
        self.assertIn("text: status.detail", scripts)
        self.assertNotIn("QC completed ", scripts)

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
        self.assertNotIn("window.statusCellStyle", scripts)

    def test_table_interactions_remain_keyboard_accessible(self):
        script = "\n".join(
            (
                self.static_source("dashboard/js/shared/data-table-ui.js"),
                self.static_source(
                    "dashboard/js/features/deliveries/table.js"
                ),
            )
        )

        self.assertIn('role: "button"', script)
        self.assertIn('tabindex: "0"', script)
        self.assertIn('event.key === "Enter"', script)
        self.assertIn('event.key === " "', script)
        self.assertIn('role: "region"', script)
        self.assertIn(
            'regionLabelledBy: "deliveries-table-title"',
            script,
        )
        self.assertIn('.find(".fixed-table-body")', script)
        self.assertIn('"aria-busy"', script)
        self.assertIn('button[name=\'columns\']', script)
        self.assertIn(".export", script)
        self.assertIn('"aria-label"', script)
        self.assertIn("title", script)
        self.assertIn("showColumns: true", script)
        self.assertIn("showButtonText: false", script)
        self.assertIn("showColumnsToggleAll: true", script)

    def test_visible_result_count_is_removed_but_live_updates_remain(self):
        response = self.client.get(reverse("deliveries"))

        self.assertEqual(response.status_code, 200)
        document = response.content.decode(response.charset)
        script = self.static_source("dashboard/js/features/deliveries/table.js")
        self.assertNotIn('id="deliveries-result-summary"', document)
        self.assertNotIn("#deliveries-result-summary", script)
        self.assertIn('id="deliveries-live-status"', document)
        self.assertIn('"Showing " + count + " of " + total', script)

    def test_semantic_table_scrolls_and_column_control_adapts_on_small_screens(self):
        """The column meaning is preserved within a focusable scroll region."""

        table_styles = "\n".join(
            self.static_source(path)
            for path in (
                "dashboard/css/ui/data-table.css",
                "dashboard/css/features/deliveries/table.css",
                "dashboard/css/features/deliveries/rows/overview.css",
                "dashboard/css/features/deliveries/rows/status.css",
                "dashboard/css/features/deliveries/rows/actions.css",
            )
        )
        responsive_styles = self.static_source(
            "dashboard/css/features/deliveries/responsive.css"
        )

        self.assertRegex(
            table_styles,
            r"#tbl-deliveries\s*\{[^}]*\bmin-width\s*:\s*940px",
        )
        shared_styles = self.static_source("dashboard/css/ui/data-table.css")
        self.assertIn(".qc-data-table-region", shared_styles)
        self.assertIn(".fixed-table-toolbar", shared_styles)
        self.assertIn(".fixed-table-toolbar .btn", shared_styles)
        self.assertIn(".fixed-table-toolbar .dropdown-menu", shared_styles)
        self.assertRegex(table_styles, r"overflow-x\s*:\s*auto")
        self.assertRegex(shared_styles, r"@media\s*\(max-width:\s*767px\)")
        self.assertNotRegex(
            shared_styles + "\n" + responsive_styles,
            r"\btd\b[^{}]*\{[^}]*\bdisplay\s*:\s*block",
        )
        self.assertIn(".delivery-row-action--primary", table_styles)
        self.assertIn(".delivery-row-action--secondary", table_styles)
        self.assertIn(".delivery-row-action--danger", table_styles)
        self.assertIn(".delivery-row-actions__destructive", table_styles)
        self.assertRegex(
            responsive_styles,
            r"\.delivery-row-action--primary,[^{]*"
            r"\.delivery-row-action--secondary\s*\{[^}]*"
            r"min-height\s*:\s*40px",
        )
