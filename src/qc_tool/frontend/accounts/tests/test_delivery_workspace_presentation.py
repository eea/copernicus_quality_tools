"""Presentation and permission contracts for the deliveries workspace."""

import re
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.test import TestCase
from django.test import override_settings
from django.urls import Resolver404
from django.urls import resolve
from django.urls import reverse
from django.utils.html import escape

from qc_tool.frontend.accounts.authorization.permissions import (
    AccountPermission,
)
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.services.role_permissions import (
    capability_content_type,
)
from qc_tool.frontend.accounts.services.products import (
    ProductCatalogUnavailable,
)


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class DeliveryWorkspacePresentationTests(TestCase):
    """Exercise semantic UX and permission-sensitive workspace controls."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="delivery-workspace-user",
            password="test-password",
        )
        self.client.force_login(self.user)

    def workspace_sidebar(self, response):
        document = response.content.decode(response.charset)
        match = re.search(
            r'<aside\b[^>]*class="[^"]*\bworkspace-sidebar\b[^"]*"'
            r'[^>]*aria-label="Workspace navigation"[^>]*>(.*?)</aside>',
            document,
            flags=re.IGNORECASE | re.DOTALL,
        )
        self.assertIsNotNone(match, "The workspace needs a labelled sidebar.")
        return match.group(0)

    def workspace_links(self, response):
        """Return the ordered links from the navigation list, excluding help."""

        sidebar = self.workspace_sidebar(response)
        navigation = re.search(
            r'<nav\b[^>]*aria-label="QC Tool workspace"[^>]*>'
            r'(.*?)</nav>',
            sidebar,
            flags=re.IGNORECASE | re.DOTALL,
        )
        self.assertIsNotNone(navigation)

        links = []
        for anchor in re.finditer(
            r'<a\b(?P<attributes>[^>]*)>(?P<body>.*?)</a>',
            navigation.group(1),
            flags=re.IGNORECASE | re.DOTALL,
        ):
            href = re.search(
                r'\bhref="(?P<href>[^"]+)"',
                anchor.group("attributes"),
                flags=re.IGNORECASE,
            )
            self.assertIsNotNone(href)
            label = re.sub(r"<[^>]+>", " ", anchor.group("body"))
            links.append(
                (
                    href.group("href"),
                    " ".join(label.split()),
                    'aria-current="page"' in anchor.group("attributes"),
                )
            )
        return links

    def permission(self, permission):
        return Permission.objects.get(
            content_type=capability_content_type(),
            codename=permission.value,
        )

    def static_source(self, relative_path):
        """Read a collected static source used by the workspace."""

        source_path = finders.find(relative_path)
        self.assertIsNotNone(
            source_path,
            "Missing workspace static asset: {}".format(relative_path),
        )
        return Path(source_path).read_text(encoding="utf-8")

    def delivery_script_source(self):
        """Read the small delivery modules as one testable browser bundle."""

        return "\n".join(
            self.static_source(relative_path)
            for relative_path in (
                "dashboard/js/features/deliveries/formatters.js",
                "dashboard/js/features/deliveries/rows/status.js",
                "dashboard/js/features/deliveries/rows/actions.js",
                "dashboard/js/features/deliveries/rows/overview.js",
                "dashboard/js/features/deliveries/table.js",
                "dashboard/js/features/deliveries/dialogs.js",
                "dashboard/js/features/deliveries/actions.js",
                "dashboard/js/features/deliveries/polling.js",
                "dashboard/js/features/deliveries/index.js",
            )
        )

    def remove_default_capabilities(self, *permissions):
        default_group = Group.objects.get(name=Role.DEFAULT.value)
        default_group.permissions.remove(
            *(self.permission(permission) for permission in permissions)
        )

    def test_sidebar_has_the_exact_workspace_order_for_a_default_user(self):
        response = self.client.get(reverse("deliveries"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "dashboard/shared/workspace_navigation.html",
        )
        sidebar = self.workspace_sidebar(response)
        self.assertEqual(sidebar.count('aria-current="page"'), 1)
        self.assertEqual(
            self.workspace_links(response),
            [
                (reverse("dashboard_home"), "Dashboard", False),
                (reverse("deliveries"), "Deliveries", True),
                (reverse("products"), "Products", False),
                (reverse("boundaries"), "Boundaries", False),
                (reverse("api_homepage"), "API Access", False),
            ],
        )
        self.assertNotIn('href="{}"'.format(reverse("file_upload")), sidebar)
        self.assertNotIn(
            'href="{}"'.format(reverse("announcement")),
            sidebar,
        )
        self.assertNotIn(
            'href="{}"'.format(reverse("admin:index")),
            sidebar,
        )
        self.assertNotIn('role="separator"', sidebar)
        self.assertContains(
            response,
            '<a class="skip-link" href="#workspace-content">',
        )
        self.assertContains(
            response,
            '<div id="workspace-content" class="workspace-content" '
            'tabindex="-1">',
        )

        for placeholder_label in ("QC Results", "Reports", "Settings"):
            self.assertNotIn(placeholder_label, sidebar)

        hrefs = re.findall(
            r'<a\b[^>]*\bhref="([^"]+)"',
            sidebar,
            flags=re.IGNORECASE,
        )
        self.assertTrue(hrefs)
        for href in hrefs:
            with self.subTest(href=href):
                self.assertNotEqual(href, "#")
                parsed = urlsplit(href)
                if parsed.scheme or parsed.netloc:
                    self.assertEqual(parsed.scheme, "https")
                    continue
                try:
                    resolve(parsed.path)
                except Resolver404 as error:
                    self.fail(
                        "Workspace navigation points at an unknown route: "
                        "{} ({})".format(href, error)
                    )

        workspace_stylesheet = "dashboard/css/ui/workspace.css"
        self.assertIsNotNone(finders.find(workspace_stylesheet))
        self.assertEqual(
            response.content.decode(response.charset).count(
                static(workspace_stylesheet)
            ),
            1,
        )

    def test_sidebar_adds_only_the_authorized_admin_destination(self):
        configuration_user = get_user_model().objects.create_user(
            username="workspace-configuration-user",
            password="test-password",
        )
        configuration_user.user_permissions.add(
            self.permission(AccountPermission.MANAGE_CONFIGURATION)
        )
        self.client.force_login(configuration_user)

        configuration_response = self.client.get(reverse("deliveries"))
        configuration_sidebar = self.workspace_sidebar(configuration_response)
        self.assertEqual(len(self.workspace_links(configuration_response)), 5)
        self.assertNotIn(
            'href="{}"'.format(reverse("admin:index")),
            configuration_sidebar,
        )
        self.assertNotIn('role="separator"', configuration_sidebar)

        administrator = get_user_model().objects.create_user(
            username="workspace-administrator",
            password="test-password",
        )
        administrator.groups.add(Group.objects.get(name=Role.ADMIN.value))
        self.client.force_login(administrator)

        administrator_response = self.client.get(reverse("deliveries"))
        administrator_sidebar = self.workspace_sidebar(administrator_response)
        self.assertEqual(
            self.workspace_links(administrator_response)[-1],
            (reverse("admin:index"), "Admin panel", False),
        )
        self.assertEqual(len(self.workspace_links(administrator_response)), 6)
        self.assertIn('role="separator"', administrator_sidebar)

    def test_each_workspace_page_marks_only_its_own_sidebar_link_current(self):
        for route_name in (
            "dashboard_home",
            "deliveries",
            "products",
            "boundaries",
        ):
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))

                self.assertEqual(response.status_code, 200)
                current_links = [
                    href
                    for href, _label, is_current in self.workspace_links(response)
                    if is_current
                ]
                self.assertEqual(current_links, [reverse(route_name)])

    @patch(
        "qc_tool.frontend.dashboard.views.products.available_product_descriptions"
    )
    def test_products_page_lists_catalog_values_with_html_escaping(
        self,
        get_product_descriptions,
    ):
        unsafe_description = "<script>alert('catalog')</script>"
        get_product_descriptions.return_value = {
            "safe-product": "Safe product",
            "escaped-product": unsafe_description,
        }

        response = self.client.get(reverse("products"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/products/index.html")
        self.assertContains(response, "2 products available")
        self.assertContains(response, escape(unsafe_description))
        self.assertNotContains(response, unsafe_description)
        self.assertContains(response, 'id="tbl-products"')
        for field, label in (
            ("description", "Product name"),
            ("ident", "Product ident"),
            ("expected", "Total AOIs"),
            ("submitted", "Submitted"),
            ("completion_percentage", "% submitted"),
        ):
            with self.subTest(field=field):
                self.assertContains(response, 'data-field="{}"'.format(field))
                self.assertContains(response, label)

        document = response.content.decode(response.charset)
        self.assertContains(response, "<th ", count=5)
        self.assertContains(response, 'scope="col"', count=5)
        field_positions = [
            document.index('data-field="{}"'.format(field))
            for field in (
                "description",
                "ident",
                "expected",
                "submitted",
                "completion_percentage",
            )
        ]
        self.assertEqual(field_positions, sorted(field_positions))
        self.assertContains(response, 'data-switchable="false"', count=2)
        self.assertContains(response, 'data-sorter="productMetricSorter"', count=3)
        self.assertContains(response, 'data-sorter="productTextSorter"', count=2)
        self.assertContains(response, 'data-searchable="false"', count=3)
        self.assertIn("qc-data-table-region", document)
        self.assertIn("qc-data-table", document)
        self.assertIn("Product details", document)
        self.assertNotIn("products-grid", document)
        self.assertNotIn("product-card", document)
        self.assertNotIn("data-products-search", document)
        for asset in (
            "dashboard/css/bootstrap-table.min.css",
            "dashboard/css/features/products/index.css",
            "dashboard/js/features/products/index.js",
        ):
            with self.subTest(asset=asset):
                self.assertIn(asset, document)

        product_script = self.static_source(
            "dashboard/js/features/products/index.js"
        )
        product_styles = self.static_source(
            "dashboard/css/features/products/index.css"
        )
        shared_table_script = self.static_source(
            "dashboard/js/shared/data-table-ui.js"
        )
        for option in (
            "QcDataTableUi",
            "search: true",
            "showColumns: true",
            "csvExportButton",
            'buttonsOrder: ["columns", "exportView"]',
            "customSearch: productSearch",
            "window.productMetricSorter",
            "window.productTextSorter",
        ):
            with self.subTest(option=option):
                self.assertIn(option, product_script)
        self.assertIn(".products-table-region", product_styles)
        self.assertIn("--qc-data-table-min-width: 900px", product_styles)
        self.assertIn("progress::-webkit-progress-value", product_styles)
        self.assertIn("progress::-moz-progress-bar", product_styles)
        self.assertIn("content: attr(data-label)", product_styles)
        self.assertIn("function enhanceSortControls($table)", shared_table_script)
        self.assertIn("function enhanceScrollRegion($table, labels)", shared_table_script)
        self.assertIn('.find(".fixed-table-body")', shared_table_script)
        self.assertIn("function exportCsv(table, settings)", shared_table_script)
        self.assertIn('bootstrapTable("getVisibleColumns")', shared_table_script)
        self.assertIn('bootstrapTable("getData", {formatted: true})', shared_table_script)
        self.assertIn("new window.Blob", shared_table_script)
        self.assertIn("window.URL.createObjectURL", shared_table_script)
        self.assertIn('filename: "products.csv"', product_script)
        self.assertIn('event.key === "Enter"', shared_table_script)
        self.assertIn('event.key === " "', shared_table_script)
        self.assertIn('"aria-sort"', shared_table_script)
        self.assertContains(response, "Not available", count=6)

        details_link = re.search(
            r'<a\b[^>]*class="product-table__details"[^>]*>'
            r'(?P<body>.*?)</a>',
            document,
            flags=re.IGNORECASE | re.DOTALL,
        )
        self.assertIsNotNone(details_link)
        self.assertFalse(
            re.sub(r"<[^>]+>", "", details_link.group("body")).strip(),
            "The details action label must not leak into exported product names.",
        )

    @patch(
        "qc_tool.frontend.dashboard.views.products.available_product_descriptions"
    )
    def test_products_page_omits_unroutable_definition_identifiers(
        self,
        get_product_descriptions,
    ):
        get_product_descriptions.return_value = {
            "safe-product": "Safe product",
            "list": "Reserved path",
            "unsafe/product": "Unroutable product",
        }

        response = self.client.get(reverse("products"))

        self.assertContains(response, "1 product available")
        self.assertContains(response, "Safe product")
        self.assertNotContains(response, "Reserved path")
        self.assertNotContains(response, "Unroutable product")

    @patch(
        "qc_tool.frontend.dashboard.views.products.available_product_descriptions",
        side_effect=ProductCatalogUnavailable("catalog unavailable"),
    )
    def test_catalog_failure_keeps_dashboard_and_products_usable(self, _catalog):
        dashboard_response = self.client.get(reverse("dashboard_home"))
        products_response = self.client.get(reverse("products"))

        self.assertEqual(dashboard_response.status_code, 200)
        self.assertContains(
            dashboard_response,
            "Product catalog unavailable",
        )
        self.assertEqual(products_response.status_code, 200)
        self.assertContains(
            products_response,
            "Product catalog temporarily unavailable",
        )

    @patch(
        "qc_tool.frontend.dashboard.views.overview.get_boundary_version",
        return_value="Unavailable",
    )
    def test_dashboard_does_not_describe_unavailable_boundaries_as_a_date(
        self,
        _boundary_version,
    ):
        response = self.client.get(reverse("dashboard_home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Boundary package unavailable")
        self.assertContains(response, "Boundary package date")
        self.assertNotContains(response, "from Unavailable")

    @override_settings(SUBMISSION_ENABLED=True)
    def test_upload_and_actions_follow_effective_permissions(self):
        permitted_response = self.client.get(reverse("deliveries"))

        self.assertContains(permitted_response, "Upload delivery")
        self.assertContains(
            permitted_response,
            'id="btn-qc-multi" class="btn btn-qc-success"',
        )
        self.assertContains(permitted_response, 'id="btn-delete-multi"')
        self.assertContains(permitted_response, 'id="btn-submit-multi"')
        self.assertContains(
            permitted_response,
            'id="delivery-selection-summary" aria-live="polite"',
        )
        self.assertContains(permitted_response, "No deliveries selected")
        self.assertContains(
            permitted_response,
            "Select eligible deliveries on this page",
        )
        self.assertContains(permitted_response, 'id="btn-clear-selection"')
        self.assertContains(permitted_response, 'id="delivery-bulk-actions"')
        self.assertContains(permitted_response, 'data-checkbox="true"')
        self.assertContains(permitted_response, "Deliveries and QC jobs")

        self.remove_default_capabilities(AccountPermission.RUN_QC)
        no_qc_response = self.client.get(reverse("deliveries"))

        self.assertNotContains(no_qc_response, 'id="btn-qc-multi"')
        self.assertContains(no_qc_response, 'id="btn-delete-multi"')
        self.assertContains(no_qc_response, 'id="btn-submit-multi"')

        self.remove_default_capabilities(
            AccountPermission.UPLOAD_DELIVERY,
            AccountPermission.DELETE_DELIVERY,
            AccountPermission.SUBMIT_DELIVERY,
        )
        restricted_response = self.client.get(reverse("deliveries"))

        self.assertEqual(restricted_response.status_code, 200)
        self.assertNotContains(
            restricted_response,
            'href="{}"'.format(reverse("file_upload")),
        )
        self.assertNotContains(restricted_response, 'id="btn-qc-multi"')
        self.assertNotContains(restricted_response, 'id="btn-delete-multi"')
        self.assertNotContains(restricted_response, 'id="btn-submit-multi"')
        self.assertNotContains(
            restricted_response,
            'id="delivery-selection-summary"',
        )
        self.assertNotContains(
            restricted_response,
            'id="btn-clear-selection"',
        )
        self.assertNotContains(restricted_response, 'data-checkbox="true"')
        self.assertNotContains(
            restricted_response,
            'id="delivery-bulk-actions"',
        )

    def test_delivery_action_assets_keep_a_clear_action_hierarchy(self):
        stylesheet = self.static_source(
            "dashboard/css/ui/actions.css"
        )
        row_styles = self.static_source(
            "dashboard/css/features/deliveries/rows/actions.css"
        )
        script = self.static_source(
            "dashboard/js/features/deliveries/rows/actions.js"
        )

        self.assertIn(".qc-shell .btn-qc-primary", stylesheet)
        self.assertIn(".qc-shell .btn-qc-quiet", stylesheet)
        self.assertIn(".qc-shell .btn-qc--compact", stylesheet)

        for predicate, action_class in (
            ("canRunQc(row)", "delivery-row-qc"),
            ("canSubmit(row)", "submit-delivery-button"),
            ("canDelete(row)", "delete-button"),
        ):
            with self.subTest(action=predicate):
                self.assertIn(predicate, script)
                self.assertIn(action_class, script)

        self.assertIn("delivery-row-action--primary", script)
        self.assertIn("delivery-row-action--secondary", script)
        self.assertIn("delivery-row-action--danger", script)
        self.assertIn("delivery-row-actions__destructive", script)
        self.assertIn('action !== "delete" && !primaryAssigned', script)
        self.assertIn("primaryAssigned = true", script)
        self.assertIn("appendDelete($destructive, row, filename)", script)
        self.assertNotIn("btn-qc-success", script)
        self.assertNotIn("btn-qc-danger-outline", script)
        self.assertIn(".delivery-row-action--primary", row_styles)
        self.assertIn(".delivery-row-action--secondary", row_styles)
        self.assertIn(".delivery-row-action--danger", row_styles)
        self.assertIn(".delivery-row-actions__destructive", row_styles)
        self.assertIn(
            "border-radius: var(--qc-radius-small)",
            row_styles,
        )
        self.assertNotIn("box-shadow", row_styles)
        self.assertNotIn("disabledAction", script)

    def test_bulk_selection_script_describes_page_local_selection(self):
        script = self.delivery_script_source()

        self.assertIn("selected on this page", script)
        self.assertIn("#btn-clear-selection", script)
        self.assertIn("eligible === total", script)
        self.assertIn('.prop("disabled", !allEligible)', script)
        self.assertIn("#delivery-selection-guidance", script)

    def test_status_filters_use_semantic_term_and_count_pairs(self):
        response = self.client.get(reverse("deliveries"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            '<nav id="delivery-status-filters" '
            'class="delivery-status-filters" '
            'aria-label="Filter deliveries by status">',
        )
        for status, label in (
            ("all", "All"),
            ("not_validated", "Not validated"),
            ("running", "Running"),
            ("passed", "Passed"),
            ("failed", "Failed"),
            ("submitted", "Submitted"),
        ):
            with self.subTest(label=label):
                self.assertContains(response, label)
                self.assertContains(
                    response,
                    'data-delivery-status-count="{}"'.format(status),
                )

        summary_response = self.client.get(reverse("deliveries_json"))
        self.assertEqual(summary_response.status_code, 200)
        self.assertEqual(
            summary_response.json()["status_counts"],
            {
                "all": 0,
                "not_validated": 0,
                "running": 0,
                "passed": 0,
                "failed": 0,
                "submitted": 0,
            },
        )

    def test_delivery_page_has_no_api_credential_management_controls(self):
        response = self.client.get(reverse("deliveries"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response,
            'href="{}#api-tokens"'.format(reverse("account_settings")),
        )
        self.assertNotContains(
            response,
            'action="{}"'.format(reverse("api_token_create")),
        )
        self.assertNotContains(response, 'class="api-credential-form"')

    def test_page_has_one_main_heading_and_an_accessible_table(self):
        response = self.client.get(reverse("deliveries"))

        self.assertEqual(response.status_code, 200)
        document = response.content.decode(response.charset)
        self.assertEqual(document.count("<main"), 1)
        self.assertEqual(document.count("<h1"), 1)

        table = re.search(
            r'<table\b[^>]*\bid="tbl-deliveries"[^>]*>',
            document,
            flags=re.IGNORECASE,
        )
        self.assertIsNotNone(table)
        table_end = document.find("</table>", table.end())
        self.assertNotEqual(table_end, -1)
        self.assertIn(
            '<caption class="sr-only">Deliveries with product and AOI context, '
            "upload details, job status, job history, and available actions</caption>",
            document[table.end() : table_end],
        )
        self.assertIn(
            'aria-describedby="deliveries-table-description"',
            table.group(0),
        )
        self.assertIn("qc-data-table", table.group(0))

        toolbar = re.search(
            r'<[^>]+\bid="delivery-selection-toolbar"[^>]*>',
            document,
            flags=re.IGNORECASE,
        )
        self.assertIsNotNone(toolbar)
        self.assertRegex(toolbar.group(0), r"\bhidden(?:\s|>|=)")
        toolbar_end = document.find(
            '<p id="deliveries-live-status"',
            toolbar.end(),
        )
        self.assertNotEqual(toolbar_end, -1)
        toolbar_markup = document[toolbar.start() : toolbar_end]
        self.assertIn(
            'role="group" aria-label="Selected delivery actions"',
            toolbar_markup,
        )
        self.assertNotIn('id="btn-export"', toolbar_markup)
        self.assertNotIn('id="btn-export"', document)
        self.assertNotIn("Export view", document)
        self.assertNotIn("API credential", toolbar_markup)
