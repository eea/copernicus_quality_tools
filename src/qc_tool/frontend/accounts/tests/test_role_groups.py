from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import connection
from django.test import TestCase

from qc_tool.frontend.accounts.authorization.roles import Role


role_group_migration = import_module(
    "qc_tool.frontend.accounts.migrations.0001_create_role_groups"
)
region_scope_migration = import_module(
    "qc_tool.frontend.accounts.migrations."
    "0003_userregiongrant_region_permissions"
)


class RoleGroupMigrationTests(TestCase):
    def test_upgrade_replaces_the_historical_country_role(self):
        self.assertIn(
            region_scope_migration.LEGACY_ROLE_NAME,
            role_group_migration.ROLE_NAMES,
        )
        self.assertEqual(
            region_scope_migration.REGION_ROLE_NAME,
            Role.REGION_MANAGER.value,
        )
        self.assertFalse(
            Group.objects.filter(
                name=region_scope_migration.LEGACY_ROLE_NAME,
            ).exists()
        )

    def test_migration_seeds_every_canonical_role_group(self):
        seeded_names = set(
            Group.objects.filter(name__in=Role.values()).values_list(
                "name",
                flat=True,
            )
        )

        self.assertEqual(seeded_names, set(Role.values()))

    def test_migration_upgrades_existing_memberships_without_touching_others(self):
        user = get_user_model().objects.create_user(username="legacy-user")
        membership_model = user.groups.through
        membership_model.objects.filter(user_id=user.pk).delete()
        legacy_product = Group.objects.create(name="product_admin")
        unrelated = Group.objects.create(name="unrelated-business-group")
        user.groups.add(legacy_product, unrelated)

        role_group_migration.create_role_groups(
            apps,
            SimpleNamespace(connection=connection),
        )

        self.assertEqual(
            set(user.groups.values_list("name", flat=True)),
            {
                Role.DEFAULT.value,
                Role.PRODUCT_MANAGER.value,
                unrelated.name,
            },
        )
        self.assertFalse(Group.objects.filter(name="product_admin").exists())
        self.assertTrue(Group.objects.filter(pk=unrelated.pk).exists())
