from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase

from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import UserProfile
from qc_tool.frontend.accounts.models import UserRegionGrant
from qc_tool.frontend.accounts.services.role_permissions import (
    capability_content_type,
)


region_migration = import_module(
    "qc_tool.frontend.accounts.migrations."
    "0003_userregiongrant_region_permissions"
)


class RegionScopeMigrationTests(TestCase):
    def create_profile(self, user, country):
        UserProfile.objects.create(user=user, country=country)

    def test_upgrade_merges_collisions_and_backfills_exact_grants_idempotently(
        self,
    ):
        user_model = get_user_model()
        old_manager = user_model.objects.create_user(username="old-manager")
        current_manager = user_model.objects.create_user(
            username="current-manager"
        )
        old_direct = user_model.objects.create_user(username="old-direct")
        rename_direct = user_model.objects.create_user(username="rename-direct")
        unaffected = user_model.objects.create_user(username="unaffected")

        legacy_group = Group.objects.create(
            name=region_migration.LEGACY_ROLE_NAME,
        )
        region_group = Group.objects.get(name=Role.REGION_MANAGER.value)
        old_manager.groups.add(legacy_group)
        current_manager.groups.add(region_group)

        content_type = capability_content_type()
        old_delivery_permission = Permission.objects.create(
            content_type=content_type,
            codename="view_country_deliveries",
            name="Legacy country deliveries",
        )
        region_delivery_permission = Permission.objects.get(
            content_type=content_type,
            codename=AccountPermission.VIEW_REGION_DELIVERIES.value,
        )
        old_direct.user_permissions.add(old_delivery_permission)
        current_manager.user_permissions.add(region_delivery_permission)

        Permission.objects.filter(
            content_type=content_type,
            codename=AccountPermission.VIEW_REGION_AGGREGATE_REPORT.value,
        ).delete()
        old_report_permission = Permission.objects.create(
            content_type=content_type,
            codename="view_country_aggregate_report",
            name="Legacy country report",
        )
        rename_direct.user_permissions.add(old_report_permission)

        unrelated_permission = Permission.objects.exclude(
            content_type=content_type,
        ).first()
        legacy_group.permissions.add(unrelated_permission)

        exact_codes = {
            old_manager: " AOI 42 ",
            current_manager: "CZ-002",
            old_direct: "cz-003",
            rename_direct: "CZ-004",
            unaffected: "SHOULD-NOT-BACKFILL",
        }
        for user, code in exact_codes.items():
            self.create_profile(user, code)

        schema_editor = SimpleNamespace(connection=connection)
        region_migration.migrate_country_scope_to_regions(apps, schema_editor)
        region_migration.migrate_country_scope_to_regions(apps, schema_editor)

        self.assertFalse(
            Group.objects.filter(name=region_migration.LEGACY_ROLE_NAME).exists()
        )
        region_group.refresh_from_db()
        self.assertTrue(region_group.user_set.filter(pk=old_manager.pk).exists())
        self.assertTrue(
            region_group.permissions.filter(pk=unrelated_permission.pk).exists()
        )

        self.assertFalse(
            Permission.objects.filter(
                content_type=content_type,
                codename__in={
                    "view_country_deliveries",
                    "view_country_aggregate_report",
                },
            ).exists()
        )
        region_delivery_permission = Permission.objects.get(
            content_type=content_type,
            codename=AccountPermission.VIEW_REGION_DELIVERIES.value,
        )
        region_report_permission = Permission.objects.get(
            content_type=content_type,
            codename=AccountPermission.VIEW_REGION_AGGREGATE_REPORT.value,
        )
        self.assertTrue(
            old_direct.user_permissions.filter(
                pk=region_delivery_permission.pk,
            ).exists()
        )
        self.assertTrue(
            rename_direct.user_permissions.filter(
                pk=region_report_permission.pk,
            ).exists()
        )

        for user in (old_manager, current_manager, old_direct, rename_direct):
            with self.subTest(user=user.username):
                self.assertEqual(
                    set(
                        UserRegionGrant.objects.filter(user=user).values_list(
                            "aoi_code",
                            flat=True,
                        )
                    ),
                    {exact_codes[user]},
                )
        self.assertFalse(
            UserRegionGrant.objects.filter(user=unaffected).exists()
        )
