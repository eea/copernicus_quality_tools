import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from qc_tool.frontend.accounts.authentication.api_keys import issue_or_rotate_api_key
from qc_tool.frontend.dashboard.models import Delivery


class ApiDeliveryRegistrationSecurityTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="api-owner")
        self.raw_key = issue_or_rotate_api_key(self.user)
        self.authorization = f"Bearer {self.raw_key}"
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.media_root = Path(self.temp_dir.name)
        self.user_root = self.media_root / self.user.username
        self.user_root.mkdir()

    def post_registration(self, uploaded_file):
        with override_settings(MEDIA_ROOT=str(self.media_root)):
            return self.client.post(
                reverse("api_register_delivery"),
                data=json.dumps({"uploaded_file": str(uploaded_file)}),
                content_type="application/json",
                HTTP_AUTHORIZATION=self.authorization,
            )

    def test_cannot_register_a_file_outside_the_authenticated_users_directory(self):
        other_root = self.media_root / "another-user"
        other_root.mkdir()
        other_delivery = other_root / "clc2012_delivery.zip"
        other_delivery.write_bytes(b"not-owned")

        response = self.post_registration(other_delivery)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["code"],
            "uploaded_file_outside_user_storage",
        )
        self.assertNotContains(response, str(other_delivery), status_code=403)
        self.assertFalse(Delivery.objects.exists())

    def test_registers_a_regular_zip_directly_below_the_users_directory(self):
        delivery_file = self.user_root / "clc2012_delivery.zip"
        delivery_file.write_bytes(b"delivery")

        response = self.post_registration(delivery_file)

        self.assertEqual(response.status_code, 200)
        delivery = Delivery.objects.get()
        self.assertEqual(delivery.user, self.user)
        self.assertEqual(delivery.filename, delivery_file.name)
        self.assertEqual(
            self.media_root / delivery.user.username / delivery.filename,
            delivery_file,
        )
