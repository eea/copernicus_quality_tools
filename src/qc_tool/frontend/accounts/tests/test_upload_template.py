from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse


class ResumableUploadTemplateTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username="uploader")
        self.client.force_login(user)

    def test_upload_page_uses_shared_layout_and_loads_each_runtime_once(self):
        response = self.client.get(reverse("file_upload"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/deliveries/upload.html")
        self.assertTemplateUsed(response, "dashboard/layouts/base.html")
        self.assertContains(response, "dashboard/js/jquery.min.js", count=1)
        self.assertContains(response, "dashboard/js/shared/csrf.js", count=1)
        self.assertContains(response, "dashboard/js/vendor/resumable.js", count=1)
        self.assertContains(response, "resumable-drop", count=1)
        self.assertContains(response, "resumable-browse", count=1)
        upload_client = "dashboard/js/features/deliveries/upload.js"
        self.assertContains(response, upload_client, count=1)

        upload_path = finders.find(upload_client)
        self.assertIsNotNone(upload_path)
        upload_source = Path(upload_path).read_text(encoding="utf-8")
        self.assertEqual(upload_source.count("window.qcCsrf.getToken()"), 1)
        self.assertEqual(
            upload_source.count("window.qcAuth.redirectFromPayload(message)"),
            1,
        )
        self.assertContains(
            response,
            f'<form method="post" action="{reverse("logout")}">',
            count=1,
        )

    def test_upload_fallback_remains_hidden_until_support_check_fails(self):
        response = self.client.get(reverse("file_upload"))

        self.assertEqual(response.status_code, 200)
        document = response.content.decode(response.charset)
        self.assertRegex(
            document,
            r'<div\b(?=[^>]*\bclass="[^"]*\bresumable-error\b[^"]*")'
            r'(?=[^>]*\bhidden(?:\s|=|>))[^>]*>',
        )

        stylesheet_path = finders.find(
            "dashboard/css/features/deliveries/upload.css"
        )
        self.assertIsNotNone(stylesheet_path)
        stylesheet = Path(stylesheet_path).read_text(encoding="utf-8")
        self.assertRegex(
            stylesheet,
            r"\.delivery-upload-card\s+\[hidden\]\s*\{"
            r"[^}]*\bdisplay\s*:\s*none\s*!important\s*;?[^}]*\}",
        )
