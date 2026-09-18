"""Semantic contracts for shared page headings and hierarchical breadcrumbs.

These tests intentionally inspect the document outline and link destinations,
not presentation classes or template whitespace.  Feature templates may change
their layout while the shared page chrome remains recognisable and accessible.
"""

import re
from contextlib import ExitStack
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from qc_tool.common import JOB_WAITING
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.accounts.authorization.permissions import (
    AccountPermission,
)
from qc_tool.frontend.accounts.services.role_permissions import (
    capability_content_type,
)
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.dashboard.models import Product
from qc_tool.frontend.dashboard.models import ProductRelease


WORKSPACE_PAGE_TEMPLATE = "dashboard/layouts/workspace_page.html"
BREADCRUMBS_TEMPLATE = "dashboard/shared/breadcrumbs.html"

DASHBOARD_APP_DIRECTORY = Path(__file__).resolve().parents[1]
SHARED_WORKSPACE_STYLESHEET = (
    DASHBOARD_APP_DIRECTORY
    / "static"
    / "dashboard"
    / "css"
    / "ui"
    / "workspace-content.css"
)
FEATURE_CANVAS_STYLESHEETS = {
    "Dashboard": (
        DASHBOARD_APP_DIRECTORY
        / "static"
        / "dashboard"
        / "css"
        / "features"
        / "overview",
        frozenset({"dashboard-home-page", "dashboard-page"}),
    ),
    "Deliveries": (
        DASHBOARD_APP_DIRECTORY
        / "static"
        / "dashboard"
        / "css"
        / "features"
        / "deliveries",
        frozenset(
            {
                "deliveries-page",
                "deliveries-page__container",
                "delivery-upload-page",
            }
        ),
    ),
    "QC jobs": (
        DASHBOARD_APP_DIRECTORY
        / "static"
        / "dashboard"
        / "css"
        / "features"
        / "jobs",
        frozenset(
            {"job-history-page", "job-setup-page", "job-result-page"}
        ),
    ),
    "Products": (
        DASHBOARD_APP_DIRECTORY
        / "static"
        / "dashboard"
        / "css"
        / "features"
        / "products",
        frozenset({"products-page", "product-detail-page", "product-upload-page", "product-remove-page"}),
    ),
    "Boundaries": (
        DASHBOARD_APP_DIRECTORY
        / "static"
        / "dashboard"
        / "css"
        / "features"
        / "boundaries",
        frozenset({"boundaries-page", "boundary-upload-page"}),
    ),
    "Configuration": (
        DASHBOARD_APP_DIRECTORY
        / "static"
        / "dashboard"
        / "css"
        / "features"
        / "configuration",
        frozenset({"announcement-page"}),
    ),
    "API Access": (
        DASHBOARD_APP_DIRECTORY
        / "static"
        / "dashboard"
        / "css"
        / "features"
        / "api_access",
        frozenset({"api-docs-page", "api-docs-main"}),
    ),
}
CANVAS_PROPERTIES = frozenset(
    {"background", "background-color", "background-image"}
)
SHARED_CARD_PROPERTIES = frozenset(
    {"border", "border-radius", "background", "background-color", "box-shadow"}
)


class _Element:
    """A deliberately small HTML element tree for semantic test queries."""

    def __init__(self, tag, attrs, *, parent=None):
        self.tag = tag
        self.attrs = dict(attrs)
        self.parent = parent
        self.children = []

    def descendants(self, tag=None, *, include_self=False):
        if include_self and (tag is None or self.tag == tag):
            yield self
        for child in self.children:
            if not isinstance(child, _Element):
                continue
            if tag is None or child.tag == tag:
                yield child
            yield from child.descendants(tag)

    @property
    def text(self):
        parts = []

        def collect(element):
            for child in element.children:
                if isinstance(child, _Element):
                    if child.attrs.get("aria-hidden") == "true":
                        continue
                    collect(child)
                else:
                    parts.append(child)

        collect(self)
        return " ".join("".join(parts).split())

    def closest(self, tag):
        element = self.parent
        while element is not None:
            if element.tag == tag:
                return element
            element = element.parent
        return None


class _DocumentParser(HTMLParser):
    """Parse enough of an HTML response to query landmarks and headings."""

    VOID_ELEMENTS = frozenset(
        {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }
    )

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Element("document", ())
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        element = _Element(tag, attrs, parent=self.stack[-1])
        self.stack[-1].children.append(element)
        if tag not in self.VOID_ELEMENTS:
            self.stack.append(element)

    def handle_startendtag(self, tag, attrs):
        element = _Element(tag, attrs, parent=self.stack[-1])
        self.stack[-1].children.append(element)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)

    @classmethod
    def from_response(cls, response):
        parser = cls()
        parser.feed(response.content.decode(response.charset))
        parser.close()
        return parser.root


def _template_names(response):
    return {
        template.name
        for template in response.templates
        if getattr(template, "name", None)
    }


def _classes(element):
    """Return an element's CSS classes without exposing parser details."""

    return frozenset(element.attrs.get("class", "").split())


def _css_rules(stylesheet):
    """Yield simple CSS rules for a narrow static architecture check.

    The feature files do not use generated CSS.  Removing comments and reading
    each selector/declaration pair is sufficient here and deliberately avoids
    coupling the test suite to a CSS parser dependency.
    """

    source = re.sub(
        r"/\*.*?\*/",
        "",
        stylesheet.read_text(encoding="utf-8"),
        flags=re.DOTALL,
    )
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", source):
        selectors, declarations = match.groups()
        properties = {
            declaration.partition(":")[0].strip().casefold()
            for declaration in declarations.split(";")
            if ":" in declaration
        }
        for selector in selectors.split(","):
            yield selector.strip(), properties


def _selector_targets_page_root(selector, root_classes):
    """Identify one-compound selectors that style the page canvas itself."""

    base_selector = selector.partition(":")[0].strip()
    if not base_selector or re.search(r"[\s>+~]", base_selector):
        return False
    selector_classes = frozenset(
        re.findall(r"\.([A-Za-z_][A-Za-z0-9_-]*)", base_selector)
    )
    return bool(selector_classes & root_classes)


class SharedBreadcrumbTests(SimpleTestCase):
    def test_deep_trails_support_section_labels_and_one_current_page(self):
        ancestors = [
            {"label": "Products", "url": "/products/"},
            {"label": "Land cover", "url": "/products/land-cover/"},
            {"label": "Reports"},
            {"label": "2024", "url": "/products/land-cover/reports/2024/"},
        ]
        parser = _DocumentParser()
        parser.feed(render_to_string(
            BREADCRUMBS_TEMPLATE,
            {
                "ancestors": ancestors,
                "current_label": "Quality & coverage",
                "aria_label": "Report breadcrumb",
                "parent_label": "Ignored shorthand",
                "parent_url": "/ignored/",
            },
        ))
        document = parser.root
        navs = list(document.descendants("nav"))
        self.assertEqual(len(navs), 1)
        self.assertEqual(navs[0].attrs["aria-label"], "Report breadcrumb")
        (ordered_list,) = navs[0].descendants("ol")
        items = list(ordered_list.descendants("li"))
        self.assertEqual(
            [item.text for item in items],
            [item["label"] for item in ancestors] + ["Quality & coverage"],
        )
        self.assertEqual(
            [anchor.attrs["href"] for anchor in document.descendants("a")],
            [item["url"] for item in ancestors if "url" in item],
        )
        current = [
            element for element in document.descendants()
            if element.attrs.get("aria-current") == "page"
        ]
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0].text, "Quality & coverage")
        self.assertIs(current[0].parent, items[-1])
        self.assertFalse(list(items[-1].descendants("a")))
        separators = [
            element for element in document.descendants("span")
            if element.attrs.get("aria-hidden") == "true"
        ]
        self.assertEqual(len(separators), len(ancestors))

    def test_missing_ancestor_or_current_page_does_not_render_navigation(self):
        for context in (
            {},
            {"current_label": "Products"},
            {"ancestors": [], "current_label": "Products"},
            {"ancestors": [{"label": "Products", "url": "/products/"}]},
            {"parent_label": "Products", "parent_url": "/products/"},
            {"section_label": "Products", "section_url": "/products/"},
        ):
            with self.subTest(context=context):
                self.assertEqual(
                    render_to_string(BREADCRUMBS_TEMPLATE, context).strip(), "",
                )


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class SharedPageChromeTests(TestCase):
    """Keep navigable pages in one coherent, accessible hierarchy."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="page-chrome-owner",
            password="test-password",
        )
        self.user.user_permissions.add(
            Permission.objects.get(
                content_type=capability_content_type(),
                codename=AccountPermission.MANAGE_CONFIGURATION.value,
            )
        )
        self.delivery = Delivery.objects.create(
            user=self.user,
            filename="page-chrome-delivery.zip",
            size_bytes=1024,
            product_ident="page_chrome_product",
            product_description="Page chrome product",
        )
        UserProductGrant.objects.create(user=self.user, product_ident="page_chrome_product")
        self.job = Job.objects.create(
            delivery=self.delivery,
            job_status=JOB_WAITING,
            product_ident=self.delivery.product_ident,
            product_description=self.delivery.product_description,
        )
        self.product = Product.objects.create(
            ident=self.delivery.product_ident,
            name="Page chrome product",
            description="Product metadata used by the shared chrome test.",
        )
        ProductRelease.objects.create(
            product=self.product,
            release_key="page_chrome_release",
            revision=1,
            description="Current page chrome release",
            catalog_digest="a" * 64,
            coverage_state=ProductRelease.CoverageState.AUTHORITATIVE,
            is_current=True,
            approved_at=timezone.now(),
        )
        self.client.force_login(self.user)

    def assert_page_chrome(
        self,
        response,
        *,
        heading,
        breadcrumbs,
        action=None,
        workspace=True,
        subtitle=True,
    ):
        """Assert shared templates and stable page semantics."""

        self.assertEqual(response.status_code, 200)
        templates = _template_names(response)
        if breadcrumbs is None:
            self.assertNotIn(BREADCRUMBS_TEMPLATE, templates)
        else:
            self.assertIn(BREADCRUMBS_TEMPLATE, templates)
        if workspace:
            self.assertIn(WORKSPACE_PAGE_TEMPLATE, templates)

        document = _DocumentParser.from_response(response)
        headings = list(document.descendants("h1"))
        self.assertEqual(
            len(headings),
            1,
            "A browser page must expose exactly one primary heading.",
        )
        self.assertEqual(headings[0].text, heading)

        page_header = headings[0].closest("header")
        if workspace:
            self.assertIsNotNone(
                page_header,
                "The primary heading must belong to the shared page header.",
            )
            main_landmarks = [
                element
                for element in document.descendants("main")
                if element.attrs.get("id") == "main-content"
            ]
            self.assertEqual(
                len(main_landmarks),
                1,
                "Workspace pages must expose one canonical main canvas.",
            )
            main_landmark = main_landmarks[0]
            self.assertTrue(
                {"site-main", "workspace-page"}.issubset(
                    _classes(main_landmark)
                ),
                "The main canvas must use the shared workspace-page primitive.",
            )

            page_containers = [
                element
                for element in main_landmark.descendants()
                if "workspace-page__container" in _classes(element)
            ]
            self.assertEqual(
                len(page_containers),
                1,
                "Workspace content must use one shared page container.",
            )
            self.assertIn(
                "workspace-page__header",
                _classes(page_header),
                "The page heading must retain the shared header primitive.",
            )
            self.assertIs(
                page_header.closest("main"),
                main_landmark,
                "The shared page header must belong to the canonical canvas.",
            )
        else:
            page_header = page_header or headings[0].closest("section")
            self.assertIsNotNone(
                page_header,
                "A standalone heading must belong to a descriptive section.",
            )
        subtitles = [
            paragraph.text
            for paragraph in page_header.descendants("p")
            if paragraph.text
        ]
        if subtitle:
            self.assertTrue(
                subtitles,
                "The shared page header must explain the page with a subtitle.",
            )
        else:
            self.assertIn("delivery_summary", response.context)
        decorative_labels = [
            element
            for element in page_header.descendants()
            if any(
                label in class_name.casefold()
                for class_name in element.attrs.get("class", "").split()
                for label in ("eyebrow", "kicker")
            )
        ]
        self.assertFalse(
            decorative_labels,
            "Page headings use their title and breadcrumb without eyebrow labels.",
        )

        breadcrumb_navs = [
            element
            for element in document.descendants("nav")
            if element.attrs.get("aria-label", "").casefold() == "breadcrumb"
        ]
        if breadcrumbs is None:
            self.assertFalse(
                breadcrumb_navs,
                "The Dashboard home page does not need a self breadcrumb.",
            )
        else:
            self.assertEqual(
                len(breadcrumb_navs),
                1,
                "The page must expose one Breadcrumb navigation landmark.",
            )
            ordered_lists = list(breadcrumb_navs[0].descendants("ol"))
            self.assertEqual(
                len(ordered_lists),
                1,
                "Breadcrumbs describe an ordered hierarchy.",
            )
            items = list(ordered_lists[0].descendants("li"))
            self.assertEqual(
                tuple(item.text for item in items),
                tuple(label for label, _href in breadcrumbs),
            )
            self.assertNotIn(
                "Dashboard",
                tuple(item.text for item in items),
                "Feature breadcrumbs begin at their owning area.",
            )
            self.assertTrue(items, "The breadcrumb hierarchy cannot be empty.")

            for item, (label, href) in zip(items[:-1], breadcrumbs[:-1]):
                with self.subTest(ancestor=label):
                    anchors = list(item.descendants("a"))
                    self.assertEqual(
                        len(anchors),
                        1,
                        "Every breadcrumb ancestor must be one canonical link.",
                    )
                    self.assertEqual(anchors[0].attrs.get("href"), href)
                    self.assertNotIn(href, (None, "", "#"))
                    self.assertFalse(
                        list(self._current_elements(item)),
                        "Only the final breadcrumb may be current.",
                    )

            final_item = items[-1]
            final_label, final_href = breadcrumbs[-1]
            self.assertEqual(final_item.text, final_label)
            self.assertIsNone(final_href)
            self.assertFalse(
                list(final_item.descendants("a")),
                "The current breadcrumb is text, not a self-referential link.",
            )
            current_elements = list(self._current_elements(final_item))
            self.assertEqual(
                len(current_elements),
                1,
                "The final breadcrumb must identify the current page once.",
            )
            self.assertNotEqual(current_elements[0].tag, "a")

        if action is not None:
            action_label, action_href = action
            matching_actions = [
                anchor
                for anchor in page_header.descendants("a")
                if anchor.text == action_label
            ]
            self.assertEqual(
                len(matching_actions),
                1,
                "The shared header must expose one clear page action.",
            )
            self.assertEqual(
                matching_actions[0].attrs.get("href"),
                action_href,
            )
            self.assertNotIn(action_href, (None, "", "#"))

    @staticmethod
    def _current_elements(item):
        return (
            element
            for element in item.descendants(include_self=True)
            if element.attrs.get("aria-current") == "page"
        )

    def assert_dashboard_uses_shared_cards(self, response):
        """Keep overview content on the same card system as feature pages."""

        document = _DocumentParser.from_response(response)
        panels = [
            element
            for element in document.descendants()
            if "dashboard-panel" in _classes(element)
        ]
        self.assertTrue(panels)
        for panel in panels:
            with self.subTest(panel=panel.attrs.get("aria-labelledby")):
                self.assertIn("workspace-card", _classes(panel))
                headers = [
                    element
                    for element in panel.descendants("header")
                    if "dashboard-panel__header" in _classes(element)
                ]
                self.assertEqual(len(headers), 1)
                self.assertIn("workspace-card__header", _classes(headers[0]))

        metrics = [
            element
            for element in document.descendants()
            if "dashboard-kpi" in _classes(element)
        ]
        self.assertTrue(metrics)
        for metric in metrics:
            self.assertIn("workspace-card", _classes(metric))

    def test_public_sign_in_uses_shared_navigation_and_labelled_controls(self):
        self.client.logout()
        response = self.client.get(reverse("login"), {"next": reverse("products")})
        self.assert_page_chrome(
            response,
            heading="Sign in",
            breadcrumbs=(
                ("CLMS QC Tool", reverse("dashboard_home")),
                ("Sign in", None),
            ),
            workspace=False,
        )
        document = _DocumentParser.from_response(response)
        inputs = {
            element.attrs.get("name"): element
            for element in document.descendants("input")
        }
        labels = {
            element.attrs.get("for"): element.text
            for element in document.descendants("label")
        }
        for name, input_type, autocomplete in (
            ("username", "text", "username"),
            ("password", "password", "current-password"),
        ):
            with self.subTest(field=name):
                field = inputs[name]
                self.assertTrue(labels[field.attrs["id"]])
                self.assertEqual(field.attrs["type"], input_type)
                self.assertEqual(field.attrs["autocomplete"], autocomplete)
                self.assertIn("required", field.attrs)
                self.assertIn("form-control", _classes(field))
        self.assertIn("csrfmiddlewaretoken", inputs)
        self.assertEqual(inputs["next"].attrs["value"], reverse("products"))

    def test_account_pages_use_shared_breadcrumbs_without_workspace_navigation(self):
        for route, heading, breadcrumbs in (
            (
                "account_settings", "Account settings",
                (("CLMS QC Tool", reverse("dashboard_home")), ("Settings", None)),
            ),
            (
                "change_password", "Change password",
                (
                    ("Account", reverse("account_settings")),
                    ("Change password", None),
                ),
            ),
        ):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assert_page_chrome(
                    response,
                    heading=heading,
                    breadcrumbs=breadcrumbs,
                    workspace=False,
                )
                self.assertTemplateNotUsed(response, WORKSPACE_PAGE_TEMPLATE)

    def test_primary_authenticated_pages_share_page_chrome(self):
        with ExitStack() as patches:
            patches.enter_context(
                patch(
                    "qc_tool.frontend.dashboard.views.overview."
                    "get_boundary_version",
                    return_value="2026-08-27",
                )
            )
            patches.enter_context(
                patch(
                    "qc_tool.frontend.dashboard.views.overview."
                    "get_announcement_message",
                    return_value="",
                )
            )
            patches.enter_context(
                patch(
                    "qc_tool.frontend.dashboard.views.deliveries.pages."
                    "get_boundary_version",
                    return_value="2026-08-27",
                )
            )
            patches.enter_context(
                patch(
                    "qc_tool.frontend.dashboard.views.deliveries.pages."
                    "get_announcement_message",
                    return_value="",
                )
            )
            patches.enter_context(
                patch(
                    "qc_tool.frontend.dashboard.views.products."
                    "available_product_descriptions",
                    return_value={
                        self.product.ident: self.product.name,
                    },
                )
            )
            patches.enter_context(
                patch(
                    "qc_tool.frontend.dashboard.views.configuration."
                    "read_announcement",
                    return_value="A deterministic workspace announcement.",
                )
            )

            cases = (
                (
                    reverse("dashboard_home"),
                    "Dashboard",
                    None,
                    None,
                ),
                (
                    reverse("deliveries"),
                    "Deliveries",
                    None,
                    ("Upload delivery", reverse("file_upload")),
                ),
                (
                    reverse("file_upload"),
                    "Upload delivery",
                    (
                        ("Deliveries", reverse("deliveries")),
                        ("Upload", None),
                    ),
                    ("Back to deliveries", reverse("deliveries")),
                ),
                (
                    reverse("products"),
                    "Products",
                    None,
                    None,
                ),
                (
                    reverse("boundaries"),
                    "Boundaries",
                    None,
                    (
                        "Replace boundary package",
                        reverse("boundaries_upload"),
                    ),
                ),
                (
                    reverse("boundaries_upload"),
                    "Replace boundary package",
                    (
                        ("Boundaries", reverse("boundaries")),
                        ("Upload", None),
                    ),
                    ("Back to boundaries", reverse("boundaries")),
                ),
                (
                    reverse("announcement"),
                    "Announcement",
                    None,
                    None,
                ),
            )
            for url, heading, breadcrumbs, action in cases:
                with self.subTest(url=url):
                    response = self.client.get(url)
                    self.assert_page_chrome(
                        response,
                        heading=heading,
                        breadcrumbs=breadcrumbs,
                        action=action,
                    )
                    if url == reverse("dashboard_home"):
                        self.assert_dashboard_uses_shared_cards(response)

    def test_delivery_job_pages_share_the_delivery_hierarchy(self):
        report = {
            "job_uuid": str(self.job.job_uuid),
            "description": self.job.product_description,
            "product_ident": self.job.product_ident,
            "filename": self.delivery.filename,
            "reference_year": None,
            "job_start_date": None,
            "job_finish_date": None,
            "status": self.job.job_status,
            "error_message": None,
            "steps": [],
        }
        with patch(
            "qc_tool.frontend.dashboard.views.jobs.setup."
            "available_product_descriptions",
            return_value={self.product.ident: self.product.name},
        ), patch(
            "qc_tool.frontend.dashboard.views.jobs.results."
            "compile_job_report_data",
            return_value=report,
        ), patch(
            "qc_tool.frontend.dashboard.views.jobs.results."
            "get_announcement_message",
            return_value="",
        ):
            cases = (
                (
                    "{}?deliveries={}".format(
                        reverse("setup_job"),
                        self.delivery.pk,
                    ),
                    "New QC job",
                    (
                        ("Deliveries", reverse("deliveries")),
                        ("New QC job", None),
                    ),
                    ("Back to deliveries", reverse("deliveries")),
                ),
                (
                    reverse("job_history", args=(self.delivery.pk,)),
                    "QC job history",
                    (
                        ("Deliveries", reverse("deliveries")),
                        ("QC job history", None),
                    ),
                    ("Back to deliveries", reverse("deliveries")),
                ),
                (
                    reverse("show_result", args=(self.job.job_uuid,)),
                    "QC job result",
                    (
                        ("Deliveries", reverse("deliveries")),
                        (
                            "QC job history",
                            reverse(
                                "job_history",
                                args=(self.delivery.pk,),
                            ),
                        ),
                        ("QC job result", None),
                    ),
                    (
                        "Back to job history",
                        reverse("job_history", args=(self.delivery.pk,)),
                    ),
                ),
            )
            for url, heading, breadcrumbs, action in cases:
                with self.subTest(url=url):
                    self.assert_page_chrome(
                        self.client.get(url),
                        heading=heading,
                        breadcrumbs=breadcrumbs,
                        action=action,
                        subtitle=heading != "QC job history",
                    )

    def test_product_detail_is_a_child_of_the_product_catalog(self):
        url = reverse("product_detail", args=(self.product.ident,))

        self.assert_page_chrome(
            self.client.get(url),
            heading=self.product.name,
            breadcrumbs=(
                ("Products", reverse("products")),
                (self.product.name, None),
            ),
            action=("All products", reverse("products")),
        )

    def test_feature_styles_do_not_override_the_shared_page_canvas(self):
        """Keep page background ownership in the shared workspace stylesheet."""

        shared_canvas_rules = [
            properties
            for selector, properties in _css_rules(
                SHARED_WORKSPACE_STYLESHEET
            )
            if selector == ".workspace-page"
            and properties & CANVAS_PROPERTIES
        ]
        self.assertTrue(
            shared_canvas_rules,
            "The shared workspace stylesheet must own the page background.",
        )

        overrides = []
        for feature, (
            directory,
            root_classes,
        ) in FEATURE_CANVAS_STYLESHEETS.items():
            for stylesheet in sorted(directory.rglob("*.css")):
                for selector, properties in _css_rules(stylesheet):
                    canvas_properties = properties & CANVAS_PROPERTIES
                    if canvas_properties and _selector_targets_page_root(
                        selector,
                        root_classes,
                    ):
                        overrides.append(
                            (
                                feature,
                                stylesheet.relative_to(
                                    DASHBOARD_APP_DIRECTORY
                                ).as_posix(),
                                selector,
                                sorted(canvas_properties),
                            )
                        )

        self.assertFalse(
            overrides,
            "Feature styles must not repaint the shared page canvas: "
            f"{overrides}",
        )

    def test_dashboard_feature_css_does_not_reimplement_shared_cards(self):
        """Feature layout may compose cards but not redefine their shell."""

        overview_styles = FEATURE_CANVAS_STYLESHEETS["Dashboard"][0]
        overrides = []
        for stylesheet in sorted(overview_styles.glob("*.css")):
            for selector, properties in _css_rules(stylesheet):
                if selector not in {".dashboard-panel", ".dashboard-kpi"}:
                    continue
                primitive_properties = properties & SHARED_CARD_PROPERTIES
                if primitive_properties:
                    overrides.append(
                        (
                            stylesheet.name,
                            selector,
                            sorted(primitive_properties),
                        )
                    )

        self.assertFalse(
            overrides,
            "Dashboard components must reuse the shared card shell: "
            f"{overrides}",
        )

    def test_public_api_page_shares_canvas_without_private_workspace_chrome(
        self,
    ):
        self.client.logout()

        response = self.client.get(reverse("api_homepage"))

        self.assert_page_chrome(
            response,
            heading="CLMS QC Tool API",
            breadcrumbs=None,
            action=("Get started", "#quick-start"),
            workspace=False,
        )
        self.assertNotIn(WORKSPACE_PAGE_TEMPLATE, _template_names(response))
        document = _DocumentParser.from_response(response)
        main_landmarks = [
            element
            for element in document.descendants("main")
            if element.attrs.get("id") == "main-content"
        ]
        self.assertEqual(len(main_landmarks), 1)
        self.assertIn("workspace-page", _classes(main_landmarks[0]))
