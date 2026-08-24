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
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.accounts.models import UserProfile
from qc_tool.frontend.accounts.services.role_permissions import (
    capability_content_type,
)


product_migration = import_module(
    "qc_tool.frontend.accounts.migrations.0004_userproductgrant"
)


class ProductGrantMigrationTests(TestCase):
    def create_scoped_user(self, username, legacy_value):
        user = get_user_model().objects.create_user(username=username)
        UserProfile.objects.create(
            user=user,
            product_family=legacy_value,
        )
        return user

    def test_backfill_is_normalized_complete_for_affected_users_and_idempotent(
        self,
    ):
        manager = self.create_scoped_user("product-manager", " CLC2024 ")
        direct = self.create_scoped_user("direct-product", "GENERAL_RASTER")
        unavailable = self.create_scoped_user("legacy-product", " HRL ")
        whitespace = self.create_scoped_user("blank-product", "   ")
        unaffected = self.create_scoped_user("unaffected-product", "clc2018")

        manager_group = Group.objects.get(name=Role.PRODUCT_MANAGER.value)
        manager.groups.add(manager_group)
        whitespace.groups.add(manager_group)

        product_permission = Permission.objects.get(
            content_type=capability_content_type(),
            codename=AccountPermission.VIEW_PRODUCT_DELIVERIES.value,
        )
        report_permission = Permission.objects.get(
            content_type=capability_content_type(),
            codename=AccountPermission.VIEW_PRODUCT_AGGREGATE_REPORT.value,
        )
        direct.user_permissions.add(product_permission)
        unavailable.user_permissions.add(report_permission)

        schema_editor = SimpleNamespace(connection=connection)
        product_migration.backfill_product_grants(apps, schema_editor)
        product_migration.backfill_product_grants(apps, schema_editor)

        expected = {
            manager: "clc2024",
            direct: "general_raster",
            unavailable: "hrl",
        }
        for user, product_ident in expected.items():
            with self.subTest(user=user.username):
                self.assertEqual(
                    set(
                        UserProductGrant.objects.filter(user=user).values_list(
                            "product_ident",
                            flat=True,
                        )
                    ),
                    {product_ident},
                )

        self.assertFalse(UserProductGrant.objects.filter(user=whitespace).exists())
        self.assertFalse(UserProductGrant.objects.filter(user=unaffected).exists())
