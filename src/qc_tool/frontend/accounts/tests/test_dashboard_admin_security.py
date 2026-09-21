from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from qc_tool.frontend.dashboard.models import S3Info


class DashboardAdminCredentialTests(TestCase):
    def setUp(self):
        administrator = get_user_model().objects.create_superuser(
            username="credential-auditor",
            email="auditor@example.test",
            password="sufficient-test-password",
        )
        self.client.force_login(administrator)
        self.s3 = S3Info.objects.create(
            host="https://objects.example.test",
            credential_ref="a" * 32,
            bucketname="deliveries",
            key_prefix="incoming/delivery",
        )

    def test_s3_admin_renders_metadata_but_never_credentials(self):
        response = self.client.get(
            reverse("admin:dashboard_s3info_change", args=(self.s3.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "objects.example.test")
        self.assertContains(response, "Stored separately")
        self.assertNotContains(response, "sensitive-access-key")
        self.assertNotContains(response, "sensitive-secret-key")
        self.assertNotContains(response, 'name="access_key"')
        self.assertNotContains(response, 'name="secret_key"')

    def test_s3_admin_disables_generic_add_and_delete_workflows(self):
        self.assertEqual(
            self.client.get(reverse("admin:dashboard_s3info_add")).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse("admin:dashboard_s3info_delete", args=(self.s3.pk,))
            ).status_code,
            403,
        )
        self.assertTrue(S3Info.objects.filter(pk=self.s3.pk).exists())
