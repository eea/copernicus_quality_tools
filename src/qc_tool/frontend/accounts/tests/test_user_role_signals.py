from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from qc_tool.frontend.accounts.authorization.roles import Role


class UserRoleSignalTests(TestCase):
    def test_new_user_gets_default_role(self):
        user = get_user_model().objects.create_user(username="new-user")

        self.assertEqual(
            set(user.groups.values_list("name", flat=True)),
            {Role.DEFAULT.value},
        )

    def test_new_superuser_gets_default_and_admin_roles(self):
        user = get_user_model().objects.create_superuser(
            username="new-superuser",
            password="password",
        )

        self.assertEqual(
            set(user.groups.values_list("name", flat=True)),
            {Role.DEFAULT.value, Role.ADMIN.value},
        )

    def test_default_role_survives_group_clear_and_remove(self):
        user = get_user_model().objects.create_user(username="protected-user")
        default_group = Group.objects.get(name=Role.DEFAULT.value)
        manager_group = Group.objects.get(name=Role.REGION_MANAGER.value)
        user.groups.add(manager_group)

        user.groups.clear()
        self.assertEqual(
            set(user.groups.values_list("name", flat=True)),
            {Role.DEFAULT.value},
        )

        user.groups.remove(default_group)
        self.assertTrue(user.groups.filter(pk=default_group.pk).exists())

    def test_default_role_survives_reverse_group_removal(self):
        user = get_user_model().objects.create_user(username="reverse-user")
        default_group = Group.objects.get(name=Role.DEFAULT.value)

        default_group.user_set.remove(user)

        self.assertTrue(user.groups.filter(pk=default_group.pk).exists())

    def test_setting_manager_roles_keeps_default(self):
        user = get_user_model().objects.create_user(username="managed-user")
        manager_group = Group.objects.get(name=Role.PRODUCT_MANAGER.value)

        user.groups.set([manager_group])

        self.assertEqual(
            set(user.groups.values_list("name", flat=True)),
            {Role.DEFAULT.value, Role.PRODUCT_MANAGER.value},
        )

    def test_superuser_required_roles_survive_clear(self):
        user = get_user_model().objects.create_superuser(
            username="protected-superuser",
            password="password",
        )

        user.groups.clear()

        self.assertEqual(
            set(user.groups.values_list("name", flat=True)),
            {Role.DEFAULT.value, Role.ADMIN.value},
        )
