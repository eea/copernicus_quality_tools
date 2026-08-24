from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from qc_tool.frontend.accounts.authorization.roles import Role


class PasswordPolicyUrlTests(TestCase):
    urls = ("/change_password/", "/accounts/password_change/")

    def create_user(self, username, *, is_superuser=False):
        return get_user_model().objects.create_user(
            username=username,
            password="current-password",
            is_staff=is_superuser,
            is_superuser=is_superuser,
        )

    def test_both_urls_allow_a_default_user(self):
        self.client.force_login(self.create_user("regular-user"))

        for url in self.urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_both_urls_fail_closed_without_a_canonical_role(self):
        user = self.create_user("ungrouped-user")
        self.client.force_login(user)
        user.groups.through.objects.filter(
            user_id=user.pk,
            group__name__in=Role.values(),
        ).delete()

        for url in self.urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_admin_role_applies_at_both_urls(self):
        user = self.create_user("admin-user")
        admin_group = Group.objects.get(name=Role.ADMIN.value)
        user.groups.add(admin_group)
        self.client.force_login(user)

        for url in self.urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
