from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class ResumableUploadTemplateTests(TestCase):
    def test_upload_page_uses_shared_layout_and_loads_each_runtime_once(self):
        user = get_user_model().objects.create_user(username="uploader")
        self.client.force_login(user)

        response = self.client.get(reverse("file_upload"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/resumable_upload.html")
        self.assertTemplateUsed(response, "dashboard/base.html")
        self.assertContains(response, "dashboard/js/jquery.min.js", count=1)
        self.assertContains(response, "dashboard/js/csrf.js", count=1)
        self.assertContains(response, "dashboard/js/resumable.js", count=1)
        self.assertContains(response, 'class="resumable-drop"', count=1)
        self.assertContains(response, 'class="resumable-browse"', count=1)
        self.assertContains(response, "window.qcCsrf.getToken()", count=1)
        self.assertContains(
            response,
            "window.qcAuth.redirectFromPayload(message)",
            count=1,
        )
        self.assertContains(
            response,
            f'<form method="post" action="{reverse("logout")}">',
            count=1,
        )
