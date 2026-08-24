from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase

from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.accounts.authorization.permissions import (
    ROLE_PERMISSION_GRANTS,
)
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import ApiUser
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.accounts.models import UserProfile
from qc_tool.frontend.accounts.models import UserRegionGrant
from qc_tool.frontend.accounts.services.role_permissions import (
    capability_content_type,
)


initial_migration = import_module(
    "qc_tool.frontend.accounts.migrations.0001_initial"
)


class ConsolidatedInitialMigrationTests(TestCase):
    def test_accounts_has_one_migration_file(self):
        migration_directory = Path(initial_migration.__file__).parent
        migration_files = sorted(
            path.name
            for path in migration_directory.glob("[0-9][0-9][0-9][0-9]_*.py")
        )

        self.assertEqual(migration_files, ["0001_initial.py"])
        self.assertTrue(initial_migration.Migration.initial)

    def test_bootstrap_migrates_legacy_access_and_is_idempotent(self):
        user_model = get_user_model()
        ordinary = user_model.objects.create_user(username="ordinary")
        superuser = user_model.objects.create_superuser(
            username="root-user",
            password="password",
        )
        country_member = user_model.objects.create_user(
            username="country-member"
        )
        region_member = user_model.objects.create_user(username="region-member")
        product_member = user_model.objects.create_user(
            username="product-member"
        )
        direct_region = user_model.objects.create_user(username="direct-region")
        direct_product = user_model.objects.create_user(
            username="direct-product"
        )
        unaffected = user_model.objects.create_user(username="unaffected")

        users = (
            ordinary,
            superuser,
            country_member,
            region_member,
            product_member,
            direct_region,
            direct_product,
            unaffected,
        )
        membership_model = user_model.groups.through
        membership_model.objects.filter(
            user_id__in=[user.pk for user in users]
        ).delete()

        country_group = Group.objects.create(name="country_manager")
        region_group = Group.objects.create(name="region_manager")
        product_group = Group.objects.create(name="product_admin")
        unrelated_group = Group.objects.create(name="unrelated-business-group")
        country_member.groups.add(country_group, unrelated_group)
        region_member.groups.add(region_group)
        product_member.groups.add(product_group, unrelated_group)

        content_type = capability_content_type()
        old_country_permission = Permission.objects.create(
            content_type=content_type,
            codename="view_country_deliveries",
            name="Legacy country delivery access",
        )
        region_report_permission = Permission.objects.get(
            content_type=content_type,
            codename=AccountPermission.VIEW_REGION_AGGREGATE_REPORT.value,
        )
        product_permission = Permission.objects.get(
            content_type=content_type,
            codename=AccountPermission.VIEW_PRODUCT_DELIVERIES.value,
        )
        unrelated_permission = Permission.objects.exclude(
            content_type=content_type,
        ).first()
        country_group.permissions.add(
            old_country_permission,
            unrelated_permission,
        )
        product_group.permissions.add(unrelated_permission)
        direct_region.user_permissions.add(region_report_permission)
        direct_product.user_permissions.add(product_permission)

        profile_values = {
            country_member: (" AOI 42 ", None),
            region_member: ("cz-003", None),
            direct_region: ("CZ-004", None),
            product_member: (None, " CLC2024 "),
            direct_product: (None, "GENERAL_RASTER"),
            unaffected: ("SHOULD-NOT-BACKFILL", "UNMANAGED_PRODUCT"),
        }
        for user, (country, product_family) in profile_values.items():
            UserProfile.objects.create(
                user=user,
                country=country,
                product_family=product_family,
            )

        ApiUser.objects.create(user=ordinary, api_key="PLAINTEXT-LEGACY-KEY")
        valid_digest = "sha256$" + ("a" * 64)
        ApiUser.objects.create(user=superuser, api_key=valid_digest)

        existing_region_grant = UserRegionGrant.objects.create(
            user=region_member,
            aoi_code="existing-region",
            created_by=ordinary,
        )
        existing_product_grant = UserProductGrant.objects.create(
            user=product_member,
            product_ident="existing-product",
            created_by=ordinary,
        )
        grant_snapshot = {
            "region": (
                existing_region_grant.pk,
                existing_region_grant.user_id,
                existing_region_grant.aoi_code,
                existing_region_grant.created_by_id,
            ),
            "product": (
                existing_product_grant.pk,
                existing_product_grant.user_id,
                existing_product_grant.product_ident,
                existing_product_grant.created_by_id,
            ),
        }

        schema_editor = SimpleNamespace(connection=connection)
        initial_migration.bootstrap_accounts(apps, schema_editor)
        initial_migration.bootstrap_accounts(apps, schema_editor)

        self.assertFalse(ApiUser.objects.filter(user=ordinary).exists())
        self.assertEqual(
            ApiUser.objects.get(user=superuser).api_key,
            valid_digest,
        )

        self.assertEqual(
            set(Group.objects.filter(name__in=Role.values()).values_list(
                "name",
                flat=True,
            )),
            set(Role.values()),
        )
        self.assertFalse(
            Group.objects.filter(
                name__in={"country_manager", "region_manager", "product_admin"}
            ).exists()
        )
        self.assertTrue(Group.objects.filter(pk=unrelated_group.pk).exists())
        for user in users:
            with self.subTest(default_role=user.username):
                self.assertTrue(
                    user.groups.filter(name=Role.DEFAULT.value).exists()
                )
        self.assertTrue(superuser.groups.filter(name=Role.ADMIN.value).exists())
        self.assertTrue(
            product_member.groups.filter(
                name=Role.PRODUCT_MANAGER.value,
            ).exists()
        )
        self.assertTrue(product_member.groups.filter(pk=unrelated_group.pk).exists())

        final_region_permissions = set(
            Permission.objects.filter(
                content_type=content_type,
                codename__in={
                    AccountPermission.VIEW_REGION_DELIVERIES.value,
                    AccountPermission.VIEW_REGION_AGGREGATE_REPORT.value,
                },
            ).values_list("pk", flat=True)
        )
        for user in (country_member, region_member):
            with self.subTest(region_permissions=user.username):
                direct_ids = set(
                    user.user_permissions.values_list("pk", flat=True)
                )
                self.assertTrue(final_region_permissions.issubset(direct_ids))
        self.assertTrue(
            country_member.user_permissions.filter(
                pk=unrelated_permission.pk,
            ).exists()
        )
        self.assertFalse(
            Permission.objects.filter(
                content_type=content_type,
                codename="view_country_deliveries",
            ).exists()
        )

        expected_regions = {
            country_member: {" AOI 42 "},
            region_member: {"existing-region", "cz-003"},
            direct_region: {"CZ-004"},
        }
        for user, codes in expected_regions.items():
            with self.subTest(region_grants=user.username):
                self.assertEqual(
                    set(user.region_grants.values_list("aoi_code", flat=True)),
                    codes,
                )
        self.assertFalse(unaffected.region_grants.exists())

        self.assertEqual(
            set(product_member.product_grants.values_list(
                "product_ident",
                flat=True,
            )),
            {"existing-product", "clc2024"},
        )
        self.assertEqual(
            set(direct_product.product_grants.values_list(
                "product_ident",
                flat=True,
            )),
            {"general_raster"},
        )
        self.assertFalse(unaffected.product_grants.exists())

        existing_region_grant.refresh_from_db()
        existing_product_grant.refresh_from_db()
        self.assertEqual(
            (
                existing_region_grant.pk,
                existing_region_grant.user_id,
                existing_region_grant.aoi_code,
                existing_region_grant.created_by_id,
            ),
            grant_snapshot["region"],
        )
        self.assertEqual(
            (
                existing_product_grant.pk,
                existing_product_grant.user_id,
                existing_product_grant.product_ident,
                existing_product_grant.created_by_id,
            ),
            grant_snapshot["product"],
        )

        for role, expected_permissions in ROLE_PERMISSION_GRANTS.items():
            with self.subTest(role_permissions=role.value):
                actual_codenames = set(
                    Group.objects.get(name=role.value)
                    .permissions.filter(content_type=content_type)
                    .values_list("codename", flat=True)
                )
                self.assertEqual(
                    actual_codenames,
                    {permission.value for permission in expected_permissions},
                )
        self.assertTrue(
            Group.objects.get(name=Role.PRODUCT_MANAGER.value)
            .permissions.filter(pk=unrelated_permission.pk)
            .exists()
        )
