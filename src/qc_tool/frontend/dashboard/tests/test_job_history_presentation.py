"""Accessible presentation contracts for one delivery's QC job history.

These tests deliberately assert user-facing semantics instead of cosmetic
whitespace or a particular CSS implementation.  The history page may evolve
visually, but it must remain recognisably part of the Deliveries workspace and
must not expose destructive controls to read-only viewers.
"""

import html
import re

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.dashboard.models import Delivery


def _normalised_text(markup):
    """Return human-readable text without depending on template spacing."""

    without_tags = re.sub(r"<[^>]+>", " ", markup)
    return " ".join(html.unescape(without_tags).split())


def _attribute(opening_tag, name):
    match = re.search(
        r"\b{}\s*=\s*(['\"])(?P<value>.*?)\1".format(re.escape(name)),
        opening_tag,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return None if match is None else match.group("value")


def _opening_tag(document, tag_name, *, element_id=None, css_class=None):
    """Find one opening tag by stable identity, independent of attr order."""

    candidates = re.finditer(
        r"<{}\b[^>]*>".format(re.escape(tag_name)),
        document,
        flags=re.IGNORECASE | re.DOTALL,
    )
    for candidate in candidates:
        markup = candidate.group(0)
        if element_id is not None and _attribute(markup, "id") != element_id:
            continue
        classes = (_attribute(markup, "class") or "").split()
        if css_class is not None and css_class not in classes:
            continue
        return candidate
    return None


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class JobHistoryPresentationTests(TestCase):
    """Keep the delivery history understandable, accessible, and scoped."""

    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="job-history-presentation-owner",
            password="test-password",
        )
        self.delivery = Delivery.objects.create(
            user=self.owner,
            filename="long-lived-delivery.zip",
            size_bytes=2048,
            product_ident="clc2024",
            product_description="Corine Land Cover 2024",
        )
        self.url = reverse("job_history", args=(self.delivery.pk,))
        self.client.force_login(self.owner)

    def response_document(self, user=None):
        if user is not None:
            self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return response, response.content.decode(response.charset)

    def test_history_reuses_workspace_with_deliveries_marked_current(self):
        response, document = self.response_document()

        self.assertTemplateUsed(response, "dashboard/layouts/workspace.html")
        self.assertTemplateUsed(
            response,
            "dashboard/shared/workspace_navigation.html",
        )

        sidebar = _opening_tag(
            document,
            "aside",
            css_class="workspace-sidebar",
        )
        self.assertIsNotNone(sidebar, "Job history needs the workspace sidebar.")
        sidebar_end = document.find("</aside>", sidebar.end())
        self.assertNotEqual(sidebar_end, -1)
        sidebar_markup = document[sidebar.start() : sidebar_end]

        links = []
        for anchor in re.finditer(
            r"<a\b[^>]*>.*?</a>",
            sidebar_markup,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            opening = anchor.group(0).split(">", 1)[0] + ">"
            if _attribute(opening, "href") == reverse("deliveries"):
                links.append(opening)

        self.assertEqual(len(links), 1)
        self.assertEqual(_attribute(links[0], "aria-current"), "page")
        current_links = [
            anchor.group(0)
            for anchor in re.finditer(
                r"<a\b[^>]*>",
                sidebar_markup,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if _attribute(anchor.group(0), "aria-current") == "page"
        ]
        self.assertEqual(current_links, links)

    def test_heading_title_back_link_and_delivery_context_are_clear(self):
        _response, document = self.response_document()

        title = re.search(
            r"<title\b[^>]*>(?P<body>.*?)</title>",
            document,
            flags=re.IGNORECASE | re.DOTALL,
        )
        self.assertIsNotNone(title)
        title_text = _normalised_text(title.group("body"))
        self.assertIn("QC job history", title_text)
        self.assertIn("QC Tool", title_text)

        headings = re.findall(
            r"<h1\b[^>]*>(?P<body>.*?)</h1>",
            document,
            flags=re.IGNORECASE | re.DOTALL,
        )
        self.assertEqual(len(headings), 1)
        self.assertEqual(_normalised_text(headings[0]), "QC job history")

        back_links = []
        for anchor in re.finditer(
            r"<a\b[^>]*>.*?</a>",
            document,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            opening = anchor.group(0).split(">", 1)[0] + ">"
            if _attribute(opening, "href") != reverse("deliveries"):
                continue
            if _normalised_text(anchor.group(0)) == "Back to deliveries":
                back_links.append(anchor.group(0))
        self.assertEqual(
            len(back_links),
            1,
            "Job history needs one clear return action.",
        )

        visible_text = _normalised_text(document)
        for expected in (
            "Product",
            self.delivery.product_description,
            "Delivery file",
            self.delivery.filename,
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, visible_text)

    def test_history_table_has_caption_description_and_labelled_region(self):
        _response, document = self.response_document()

        table = _opening_tag(document, "table", element_id="tbl-history")
        self.assertIsNotNone(table)
        table_tag = table.group(0)
        description_id = _attribute(table_tag, "aria-describedby")
        self.assertEqual(description_id, "job-history-description")

        description = re.search(
            r"<(?P<tag>[a-z0-9]+)\b"
            r"(?=[^>]*\bid=['\"]{}['\"])[^>]*>"
            r"(?P<body>.*?)</(?P=tag)>".format(
                re.escape(description_id),
            ),
            document,
            flags=re.IGNORECASE | re.DOTALL,
        )
        self.assertIsNotNone(description)
        self.assertTrue(_normalised_text(description.group("body")))

        table_end = document.find("</table>", table.end())
        self.assertNotEqual(table_end, -1)
        table_markup = document[table.end() : table_end]
        caption = re.search(
            r"<caption\b[^>]*>(?P<body>.*?)</caption>",
            table_markup,
            flags=re.IGNORECASE | re.DOTALL,
        )
        self.assertIsNotNone(caption)
        self.assertEqual(
            _normalised_text(caption.group("body")),
            "QC runs for this delivery",
        )

        region = _opening_tag(
            document,
            "div",
            css_class="job-history-table-region",
        )
        self.assertIsNotNone(region)
        region_tag = region.group(0)
        self.assertEqual(_attribute(region_tag, "role"), "region")
        self.assertEqual(_attribute(region_tag, "tabindex"), "0")
        self.assertTrue(
            _attribute(region_tag, "aria-label")
            or _attribute(region_tag, "aria-labelledby"),
            "The scrollable table region needs an accessible name.",
        )
        self.assertLess(region.start(), table.start())

    def test_delete_controls_are_rendered_only_for_authorised_managers(self):
        owner_response, owner_document = self.response_document()

        self.assertIs(owner_response.context["can_delete_jobs"], True)
        self.assertIsNotNone(
            _opening_tag(
                owner_document,
                "button",
                element_id="btn-delete-multi",
            )
        )
        self.assertRegex(
            owner_document,
            r"\bdata-checkbox\s*=\s*['\"]true['\"]",
        )
        self.assertIsNotNone(
            _opening_tag(owner_document, "div", element_id="confirm-delete")
        )
        confirm_button = _opening_tag(
            owner_document,
            "button",
            element_id="confirm-delete-button",
        )
        self.assertIsNotNone(confirm_button)
        self.assertEqual(
            _attribute(
                _opening_tag(
                    owner_document,
                    "div",
                    element_id="confirm-delete",
                ).group(0),
                "aria-labelledby",
            ),
            "confirm-delete-title",
        )

        product_manager = get_user_model().objects.create_user(
            username="job-history-read-only-product-manager",
            password="test-password",
        )
        product_manager.groups.add(
            Group.objects.get(name=Role.PRODUCT_MANAGER.value)
        )
        UserProductGrant.objects.create(
            user=product_manager,
            product_ident=self.delivery.product_ident,
        )

        viewer_response, viewer_document = self.response_document(
            product_manager
        )

        self.assertIs(viewer_response.context["can_delete_jobs"], False)
        self.assertIsNone(
            _opening_tag(
                viewer_document,
                "button",
                element_id="btn-delete-multi",
            )
        )
        self.assertNotRegex(
            viewer_document,
            r"\bdata-checkbox\s*=\s*['\"]true['\"]",
        )
        self.assertIsNone(
            _opening_tag(viewer_document, "div", element_id="confirm-delete")
        )
