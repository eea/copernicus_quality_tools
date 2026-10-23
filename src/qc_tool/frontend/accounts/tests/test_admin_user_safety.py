"""Account administration preserves delivery identity and recovery access."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier

from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import close_old_connections, connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.services.admin_users import LAST_ADMINISTRATOR_MESSAGE
from qc_tool.frontend.dashboard.models import Delivery, Job
from qc_tool.frontend.dashboard.services import maintenance
from qc_tool.frontend.dashboard.services.uploads.paths import resolve_user_delivery_upload


def change_data(user, **changes):
    data = {
        "username": user.username, "first_name": user.first_name,
        "last_name": user.last_name, "email": user.email,
        "groups": list(user.groups.values_list("pk", flat=True)),
        "user_permissions": list(user.user_permissions.values_list("pk", flat=True)),
        "personal_access_tokens-TOTAL_FORMS": "0",
        "personal_access_tokens-INITIAL_FORMS": "0",
        "product_grants-TOTAL_FORMS": "0", "product_grants-INITIAL_FORMS": "0",
        "_save": "Save",
    }
    if user.is_active:
        data["is_active"] = "on"
    if user.is_superuser:
        data["is_superuser"] = "on"
    data.update(changes)
    return data


class AdminUserSafetyMixin:
    def setUp(self):
        super().setUp()
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.media_root = directory / "media"
        self.media_root.mkdir()
        self.enterContext(override_settings(
            MAINTENANCE_MODE=False,
            QC_TOOL_MAINTENANCE_DIR=directory / "maintenance",
            QC_TOOL_TRANSFER_DIR=directory / "transfers", MEDIA_ROOT=self.media_root,
        ))
        self.root = get_user_model().objects.create_superuser(
            username="account-safety-root", password="sufficient-test-password",
            email="root@example.test",
        )
        self.admin_group = Group.objects.get(name=Role.ADMIN.value)
        self.client.force_login(self.root)

    def role_admin(self, username, *, active=True, password="sufficient-test-password"):
        user = get_user_model().objects.create_user(username=username, password=password, is_active=active)
        user.groups.add(self.admin_group)
        user.refresh_from_db()
        return user

    def change(self, user, **changes):
        return self.client.post(reverse("admin:auth_user_change", args=[user.pk]), change_data(user, **changes))

    def assert_last_admin_error(self, response):
        self.assertContains(response, LAST_ADMINISTRATOR_MESSAGE, status_code=200)


class AdminUserSafetyTests(AdminUserSafetyMixin, TestCase):
    def test_existing_username_is_read_only_and_forged_rename_preserves_delivery_files(self):
        user = get_user_model().objects.create_user(username="retained-owner", password="owner-password")
        upload_root = self.media_root / user.username
        upload_root.mkdir()
        original = upload_root / "retained.zip"
        original.write_bytes(b"retained input")
        delivery = Delivery.objects.create(user=user, filename=original.name, size_bytes=original.stat().st_size)
        job = Job.objects.create(delivery=delivery, product_ident="test", product_description="Retained job")
        before = self.client.get(reverse("admin:auth_user_change", args=[user.pk]))
        self.assertNotContains(before, 'name="username"')
        self.assertContains(before, user.username)

        response = self.change(user, username="forged-owner", first_name="Updated", email="updated@example.test")

        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        delivery.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual(user.username, "retained-owner")
        self.assertEqual((user.first_name, user.email), ("Updated", "updated@example.test"))
        self.assertEqual(job.delivery_id, delivery.pk)
        self.assertEqual(delivery.user_id, user.pk)
        self.assertEqual(resolve_user_delivery_upload(
            delivery.filename, media_root=self.media_root, username=delivery.user.username,
        ), original)

    def test_new_accounts_still_accept_a_username(self):
        response = self.client.get(reverse("admin:auth_user_add"))
        self.assertContains(response, 'name="username"')

    def test_last_superuser_cannot_be_deactivated_or_partially_updated(self):
        before = LogEntry.objects.count()
        self.assert_last_admin_error(self.change(self.root, is_active="", first_name="Must not be saved"))
        self.root.refresh_from_db()
        self.assertTrue(self.root.is_active)
        self.assertEqual(self.root.first_name, "")
        self.assertEqual(LogEntry.objects.count(), before)

    def test_last_superuser_cannot_remove_both_superuser_and_admin_role(self):
        groups = list(self.root.groups.exclude(pk=self.admin_group.pk).values_list("pk", flat=True))
        self.assert_last_admin_error(self.change(self.root, is_superuser="", groups=groups))
        self.root.refresh_from_db()
        self.assertTrue(self.root.is_superuser)

    def test_last_role_administrator_cannot_remove_the_admin_role(self):
        operator = self.role_admin("only-role-administrator")
        get_user_model().objects.filter(pk=self.root.pk).update(is_active=False)
        self.client.force_login(operator)
        remaining_groups = list(operator.groups.exclude(pk=self.admin_group.pk).values_list("pk", flat=True))
        self.assert_last_admin_error(self.change(operator, groups=remaining_groups))
        self.assertTrue(operator.groups.filter(pk=self.admin_group.pk).exists())
        operator.refresh_from_db()
        self.assertTrue(operator.is_staff)

    def test_superuser_can_be_demoted_when_its_admin_role_preserves_access(self):
        self.root.groups.add(self.admin_group)
        response = self.change(self.root, is_superuser="")
        self.assertEqual(response.status_code, 302)
        self.root.refresh_from_db()
        self.assertFalse(self.root.is_superuser)
        self.assertTrue(self.root.is_active)
        self.assertTrue(self.root.is_staff)
        self.assertTrue(self.root.groups.filter(pk=self.admin_group.pk).exists())

    def test_another_usable_administrator_allows_deactivation(self):
        other = self.role_admin("remaining-administrator")
        response = self.change(self.root, is_active="")
        self.assertEqual(response.status_code, 302)
        self.root.refresh_from_db()
        self.assertFalse(self.root.is_active)
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)

    def test_another_usable_administrator_allows_role_removal(self):
        target = self.role_admin("retiring-administrator")
        response = self.change(target, groups=[])
        self.assertEqual(response.status_code, 302)
        target.refresh_from_db()
        self.assertTrue(target.is_active)
        self.assertFalse(target.groups.filter(pk=self.admin_group.pk).exists())
        self.assertFalse(target.is_staff)

    def test_inactive_unusable_and_manager_accounts_do_not_replace_last_admin(self):
        self.role_admin("inactive-administrator", active=False)
        self.role_admin("unusable-administrator", password=None)
        manager = get_user_model().objects.create_user(username="manager", password="manager-password")
        manager.groups.add(Group.objects.get(name=Role.PRODUCT_MANAGER.value))
        self.assert_last_admin_error(self.change(self.root, is_active=""))
        self.root.refresh_from_db()
        self.assertTrue(self.root.is_active)

    def test_last_admin_cannot_disable_password_sign_in(self):
        original = self.root.password
        response = self.client.post(reverse("admin:auth_user_password_change", args=[self.root.pk]), {
            "usable_password": "false", "unset-password": "Disable password-based authentication",
        })
        self.assert_last_admin_error(response)
        self.root.refresh_from_db()
        self.assertEqual(self.root.password, original)

    def test_another_usable_admin_allows_disabling_password_sign_in(self):
        self.role_admin("password-recovery-administrator")
        response = self.client.post(reverse("admin:auth_user_password_change", args=[self.root.pk]), {
            "usable_password": "false", "unset-password": "Disable password-based authentication",
        })
        self.assertEqual(response.status_code, 302)
        self.root.refresh_from_db()
        self.assertFalse(self.root.has_usable_password())

    def test_hard_deletion_remains_unavailable(self):
        user_admin = admin.site._registry[get_user_model()]
        self.assertFalse(user_admin.has_delete_permission(None, self.root))


class ConcurrentAdminUserSafetyTests(AdminUserSafetyMixin, TransactionTestCase):
    def test_concurrent_deactivation_cannot_remove_both_administrators(self):
        if connection.vendor != "postgresql":
            self.skipTest("Transaction advisory locks require PostgreSQL.")
        # Bootstrap this disposable installation before concurrent requests.
        # A reader racing the first state publication must fail closed; that
        # independent storage-initialization race does not test account locks.
        self.assertEqual(maintenance.read_status()["phase"], "off")
        other = self.role_admin("concurrent-administrator")
        barrier = Barrier(2)

        def deactivate(user_id):
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=user_id)
                client = Client()
                client.force_login(user)
                payload = change_data(user, is_active="")
                barrier.wait(timeout=10)
                response = client.post(reverse("admin:auth_user_change", args=[user.pk]), payload)
                return response.status_code, response.content.decode()
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(deactivate, (self.root.pk, other.pk)))
        self.assertCountEqual([status for status, _body in responses], [200, 302])
        rejected = next(body for status, body in responses if status == 200)
        self.assertIn(LAST_ADMINISTRATOR_MESSAGE, rejected)
        self.assertEqual(get_user_model().objects.filter(pk__in=(self.root.pk, other.pk), is_active=True).count(), 1)
