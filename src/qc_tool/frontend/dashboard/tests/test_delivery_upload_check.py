"""Filename warnings never reveal another uploader's deliveries."""
import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.dashboard.models import Delivery


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class DeliveryUploadCheckTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user(username="duplicate-owner")
        UserProductGrant.objects.create(user=cls.owner, product_ident="example")
        cls.other = get_user_model().objects.create_user(username="duplicate-other")
        cls.admin = get_user_model().objects.create_superuser(username="duplicate-admin", email="admin@example.test", password="unused")
        cls.own = Delivery.objects.create(user=cls.owner, filename="same.zip", size_bytes=10)
        cls.foreign = Delivery.objects.create(user=cls.other, filename="private.zip", size_bytes=10)
        Delivery.objects.create(user=cls.owner, filename="deleted.zip", size_bytes=10, is_deleted=True)

    def setUp(self):
        self.url = reverse("delivery_upload_check")
        self.client.force_login(self.owner)

    def check(self, filenames):
        return self.client.post(self.url, {"filenames": filenames}, content_type="application/json")

    def test_only_own_active_filenames_are_reported_and_linked(self):
        response = self.check(["same.zip", "private.zip", "deleted.zip", "new.zip"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        files = response.json()["files"]
        self.assertTrue(files[0]["exists"])
        self.assertTrue(files[0]["can_overwrite"])
        self.assertEqual(files[0]["delivery_id"], self.own.pk)
        self.assertEqual(files[0]["url"], reverse("job_history", args=(self.own.pk,)))
        for row in files[1:]:
            self.assertFalse(row["exists"])
            self.assertIsNone(row["delivery_id"])
            self.assertIsNone(row["date_uploaded"])
            self.assertIsNone(row["url"])
            self.assertFalse(row["can_overwrite"])

    def test_submitted_and_ambiguous_filenames_explain_why_overwrite_is_unavailable(self):
        from django.utils import timezone
        self.own.date_submitted = timezone.now()
        self.own.save(update_fields=("date_submitted",))
        row = self.check(["same.zip"]).json()["files"][0]
        self.assertFalse(row["can_overwrite"])
        self.assertIn("submitted", row["overwrite_reason"])
        Delivery.objects.create(user=self.owner, filename="same.zip", size_bytes=11)
        row = self.check(["same.zip"]).json()["files"][0]
        self.assertFalse(row["can_overwrite"])
        self.assertIn("Multiple", row["overwrite_reason"])

    def test_admin_also_checks_only_their_own_records(self):
        self.client.force_login(self.admin)
        self.assertTrue(all(not row["exists"] for row in self.check(["same.zip", "private.zip"]).json()["files"]))
        own = Delivery.objects.create(user=self.admin, filename="same.zip", size_bytes=11)
        self.assertEqual(self.check(["same.zip"]).json()["files"][0]["delivery_id"], own.pk)

    def test_validation_rejects_malformed_or_oversized_requests(self):
        for filenames in [[], ["file.zip"] * 101, ["../file.zip"], ["a\\file.zip"], [None], ["file.json"], ["a" * 256 + ".zip"]]:
            with self.subTest(filenames=filenames[:1]):
                self.assertEqual(self.check(filenames).status_code, 400)
        self.assertEqual(self.client.post(self.url, "{", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post(self.url, json.dumps({"filenames": ["a" * 66000]}), content_type="application/json").status_code, 413)
        self.assertEqual(self.client.post(self.url, {"filenames": "same.zip"}).status_code, 400)

    def test_preflight_requires_session_permission_csrf_and_post(self):
        self.client.logout()
        self.assertEqual(self.check(["same.zip"]).status_code, 401)
        self.client.force_login(self.owner)
        # Normal group removal and login saves restore the required default
        # role. Remove its join rows after login to exercise missing access.
        self.owner.groups.through.objects.filter(user_id=self.owner.pk).delete()
        self.owner.user_permissions.clear()
        self.assertEqual(self.check(["same.zip"]).status_code, 403)
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.admin)
        self.assertEqual(secure.post(self.url, {"filenames": ["same.zip"]}, content_type="application/json").status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 405)
