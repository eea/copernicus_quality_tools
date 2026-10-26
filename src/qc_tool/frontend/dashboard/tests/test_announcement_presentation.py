"""Service announcements remain readable notices, separate from maintenance."""

from html.parser import HTMLParser

from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.utils.html import escape


NOTICE = "dashboard/shared/announcements/notice.html"
CURRENT = "dashboard/shared/announcements/current.html"


class _Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


class AnnouncementPresentationTests(SimpleTestCase):
    def test_active_notice_is_named_escaped_multiline_and_read_only(self):
        message = 'Service window & status\n<script>alert("unsafe")</script>\n<a href="javascript:alert(1)">message</a>'
        html = render_to_string(NOTICE, {
            "announcement": message, "id": "service-announcement-title",
            "read_url": "/announcement/",
        })
        elements = _Elements(html).elements
        aside = next(attrs for tag, attrs in elements if tag == "aside")
        heading = next(attrs for tag, attrs in elements if tag == "h2")
        self.assertEqual(aside["aria-labelledby"], heading["id"])
        self.assertEqual(heading["id"], "service-announcement-title")
        self.assertIn("Announcement</h2>", html)
        self.assertEqual(sum(tag == "br" for tag, _attrs in elements), 2)
        for line in message.splitlines():
            self.assertIn(escape(line), html)
        self.assertFalse(any(tag in {"script", "form", "button", "input"} for tag, _attrs in elements))
        self.assertEqual([attrs["href"] for tag, attrs in elements if tag == "a"], ["/announcement/"])
        self.assertFalse(any(name.startswith("data-maintenance-") for _tag, attrs in elements for name in attrs))
        self.assertTrue(all(attrs.get("aria-hidden") == "true" for tag, attrs in elements if tag == "svg"))

    def test_empty_compact_notice_does_not_leave_a_heading_or_action(self):
        for message in (None, ""):
            with self.subTest(message=message):
                self.assertEqual(render_to_string(NOTICE, {
                    "announcement": message, "id": "unused-title", "read_url": "/announcement/",
                }).strip(), "")

    def test_current_active_message_uses_the_shared_notice(self):
        with self.assertTemplateUsed(NOTICE):
            html = render_to_string(CURRENT, {
                "announcement_available": True, "announcement": "First line\nSecond line",
            })
        elements = _Elements(html).elements
        aside = next(attrs for tag, attrs in elements if tag == "aside")
        heading = next(attrs for tag, attrs in elements if tag == "h2")
        self.assertEqual(aside["aria-labelledby"], heading["id"])
        self.assertEqual(sum(tag == "br" for tag, _attrs in elements), 1)

    def test_current_empty_and_unavailable_states_remain_distinct(self):
        for available, message, expected in (
            (True, "", "There is no active announcement."),
            (False, "Stale message must not be shown", "temporarily unavailable"),
        ):
            with self.subTest(available=available), self.assertTemplateNotUsed(NOTICE):
                html = render_to_string(CURRENT, {
                    "announcement_available": available, "announcement": message,
                })
                self.assertIn(expected, html)
                self.assertNotIn("Stale message must not be shown", html)
                self.assertFalse(any(tag in {"aside", "a", "form"} for tag, _attrs in _Elements(html).elements))
