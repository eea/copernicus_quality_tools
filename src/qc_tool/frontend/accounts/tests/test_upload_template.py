from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse

from qc_tool.frontend.accounts.models import UserProductGrant

class ResumableUploadTemplateTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username="uploader")
        UserProductGrant.objects.create(user=user, product_ident="example")
        self.client.force_login(user)

    def test_upload_page_uses_shared_layout_and_loads_each_runtime_once(self):
        response = self.client.get(reverse("file_upload"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/deliveries/upload.html")
        self.assertTemplateUsed(response, "dashboard/layouts/base.html")
        self.assertContains(response, "dashboard/js/jquery.min.js", count=1)
        self.assertContains(response, "dashboard/js/shared/csrf.js", count=1)
        self.assertContains(response, "dashboard/js/vendor/resumable.js", count=1)
        self.assertTemplateUsed(response, "dashboard/layouts/upload_page.html")
        self.assertTemplateUsed(response, "dashboard/shared/uploads/picker.html")
        self.assertContains(response, "data-upload-picker ", count=1)
        self.assertContains(response, 'data-upload-browse aria-describedby=', count=1)
        upload_client = "dashboard/js/features/deliveries/upload.js"
        self.assertContains(response, upload_client, count=1)

        upload_path = finders.find(upload_client)
        self.assertIsNotNone(upload_path)
        upload_source = Path(upload_path).read_text(encoding="utf-8")
        self.assertEqual(upload_source.count("window.qcCsrf.getToken()"), 2)
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
            r'<div\b(?=[^>]*\bdata-upload-unsupported\b)'
            r'(?=[^>]*\bhidden(?:\s|=|>))[^>]*>',
        )

        stylesheet_path = finders.find(
            "dashboard/css/ui/uploads.css"
        )
        self.assertIsNotNone(stylesheet_path)
        stylesheet = Path(stylesheet_path).read_text(encoding="utf-8")
        self.assertRegex(
            stylesheet,
            r"\.qc-upload\s+\[hidden\]\s*\{"
            r"[^}]*\bdisplay\s*:\s*none\s*!important\s*;?[^}]*\}",
        )

    def test_upload_progress_is_owned_by_file_rows_and_announces_phase_changes(self):
        response = self.client.get(reverse("file_upload"))

        self.assertNotContains(response, "Uploading deliveries")
        self.assertNotContains(response, "delivery-upload-overall-progress")
        self.assertNotContains(response, 'role="progressbar"')
        self.assertContains(response, 'aria-label="Files to add"', count=1)
        # Queue updates must not re-read every filename/percentage to assistive
        # technology. A dedicated status region announces upload phase changes.
        self.assertContains(
            response,
            '<div class="sr-only" data-upload-announcement '
            'role="status" aria-atomic="true"></div>',
            count=1,
            html=True,
        )
        self.assertContains(response, "open Deliveries to run quality checks")

    def test_all_upload_pages_load_shared_components_once_before_their_adapter(self):
        admin = get_user_model().objects.create_superuser(
            username="upload-component-admin", email="admin@example.test", password="unused",
        )
        self.client.force_login(admin)
        for route, feature in (
            ("file_upload", "deliveries"),
            ("boundaries_upload", "boundaries"),
            ("product_upload", "products"),
        ):
            with self.subTest(feature=feature):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "dashboard/layouts/upload_page.html")
                self.assertTemplateUsed(response, "dashboard/shared/uploads/picker.html")
                self.assertContains(response, "dashboard/css/ui/uploads.css", count=1)
                self.assertContains(response, "dashboard/js/shared/uploads.js", count=1)
                self.assertNotContains(response, f"dashboard/css/features/{feature}/upload.css")
                content = response.content.decode(response.charset)
                self.assertLess(
                    content.index("dashboard/js/shared/uploads.js"),
                    content.index(f"dashboard/js/features/{feature}/upload.js"),
                )
                if feature in {"products", "deliveries"}:
                    self.assertTemplateUsed(response, "dashboard/layouts/upload_queue_page.html")
                    self.assertTemplateUsed(response, "dashboard/shared/uploads/queue.html")
                    self.assertContains(response, "dashboard/js/shared/upload-queue.js", count=1)
                    self.assertContains(response, "data-upload-add-all", count=1)
                    self.assertLess(
                        content.index("dashboard/js/shared/upload-queue.js"),
                        content.index(f"dashboard/js/features/{feature}/upload.js"),
                    )
