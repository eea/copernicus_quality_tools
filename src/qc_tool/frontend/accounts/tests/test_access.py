from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.test import TestCase

from qc_tool.frontend.accounts.authorization.access import access_for
from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.accounts.authorization.permissions import DEFAULT_PERMISSIONS
from qc_tool.frontend.accounts.authorization.permissions import (
    PRODUCT_MANAGER_PERMISSIONS,
)
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.authorization.roles import roles_for
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.accounts.models import UserRegionGrant
from qc_tool.frontend.accounts.services.role_permissions import (
    capability_content_type,
)


class AccountAccessTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="policy-user",
            password="initial-password",
        )

    def add_roles(self, *roles):
        groups = [
            Group.objects.get_or_create(name=role.value)[0] for role in roles
        ]
        self.user.groups.add(*groups)

    def grant_permissions(self, *permissions):
        direct_permissions = Permission.objects.filter(
            content_type=capability_content_type(),
            codename__in=[permission.value for permission in permissions],
        )
        self.user.user_permissions.add(*direct_permissions)

    def test_default_role_grants_normal_application_capabilities(self):
        access = access_for(self.user)

        self.assertEqual(roles_for(self.user), frozenset({Role.DEFAULT}))
        self.assertTrue(access.is_default_user)
        self.assertFalse(access.is_administrator)
        self.assertEqual(access.permissions, DEFAULT_PERMISSIONS)
        self.assertTrue(access.can_view_deliveries)
        self.assertTrue(access.can_upload)
        self.assertTrue(access.can_run_qc)
        self.assertTrue(access.can_delete)
        self.assertTrue(access.can_submit)
        self.assertTrue(access.can_change_password)
        self.assertTrue(access.can_manage_own_account)
        self.assertTrue(access.can_manage_api_credential)
        self.assertTrue(access.can_access_account_settings)
        self.assertFalse(access.can_manage_configuration)
        self.assertFalse(access.can_access_django_admin)
        self.assertFalse(
            access.allows(AccountPermission.MANAGE_CONFIGURATION)
        )

    def test_product_role_and_direct_region_permissions_add_scoped_visibility(self):
        self.add_roles(Role.PRODUCT_MANAGER)
        self.grant_permissions(
            AccountPermission.VIEW_REGION_DELIVERIES,
            AccountPermission.VIEW_REGION_AGGREGATE_REPORT,
        )
        self.user.groups.add(Group.objects.create(name="unrecognized-role"))
        UserProductGrant.objects.create(
            user=self.user,
            product_ident="clc2024",
        )
        UserRegionGrant.objects.create(user=self.user, aoi_code="CZ")

        access = access_for(self.user)

        self.assertEqual(
            roles_for(self.user),
            frozenset(
                {
                    Role.DEFAULT,
                    Role.PRODUCT_MANAGER,
                }
            ),
        )
        self.assertTrue(access.is_product_manager)
        self.assertEqual(
            access.permissions,
            DEFAULT_PERMISSIONS
            | PRODUCT_MANAGER_PERMISSIONS
            | {
                AccountPermission.VIEW_REGION_DELIVERIES,
                AccountPermission.VIEW_REGION_AGGREGATE_REPORT,
            },
        )
        self.assertTrue(access.can_view_region_deliveries)
        self.assertTrue(access.can_view_product_deliveries)
        self.assertTrue(access.can_view_other_users_deliveries)
        self.assertEqual(access.delivery_list_heading, "Managed Deliveries")
        self.assertTrue(access.can_manage_user(self.user.pk))
        self.assertFalse(access.can_manage_user(self.user.pk + 1))

    def test_admin_group_grants_every_permission(self):
        self.add_roles(Role.ADMIN)

        access = access_for(self.user)

        self.assertTrue(access.is_administrator)
        self.assertEqual(access.permissions, frozenset(AccountPermission))
        self.assertTrue(access.can_view_other_users_deliveries)
        self.assertTrue(access.can_manage_configuration)
        self.assertTrue(access.can_access_django_admin)
        self.assertEqual(access.delivery_list_heading, "All Deliveries")
        self.assertTrue(access.can_manage_user(self.user.pk + 1))

    def test_superuser_gets_every_permission(self):
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save(update_fields=["is_staff", "is_superuser"])

        access = access_for(self.user)

        self.assertTrue(access.is_administrator)
        self.assertIn(Role.ADMIN, access.roles)
        self.assertEqual(access.permissions, frozenset(AccountPermission))

    def test_user_without_a_canonical_group_fails_closed(self):
        membership_model = self.user.groups.through
        membership_model.objects.filter(user_id=self.user.pk).delete()
        self.user.groups.add(Group.objects.create(name="unknown-role"))

        access = access_for(self.user)

        self.assertTrue(access.is_authenticated)
        self.assertEqual(access.roles, frozenset())
        self.assertEqual(access.permissions, frozenset())
        self.assertFalse(access.can_view_deliveries)
        self.assertFalse(access.can_view_other_users_deliveries)

    def test_region_scope_permission_does_not_depend_on_default_bundle(self):
        self.grant_permissions(AccountPermission.VIEW_REGION_DELIVERIES)
        UserRegionGrant.objects.create(user=self.user, aoi_code="CZ")
        membership_model = self.user.groups.through
        default_group = Group.objects.get(name=Role.DEFAULT.value)
        membership_model.objects.filter(
            user_id=self.user.pk,
            group_id=default_group.pk,
        ).delete()

        access = access_for(self.user)

        self.assertFalse(access.can_view_deliveries)
        self.assertTrue(access.can_view_region_deliveries)
        self.assertEqual(
            access.permissions,
            frozenset({AccountPermission.VIEW_REGION_DELIVERIES}),
        )

    def test_direct_permissions_add_capabilities_without_manager_groups(self):
        UserProductGrant.objects.create(
            user=self.user,
            product_ident="clc2024",
        )
        UserRegionGrant.objects.create(user=self.user, aoi_code="CZ")
        content_type = capability_content_type()
        direct_permissions = Permission.objects.filter(
            content_type=content_type,
            codename__in={
                AccountPermission.MANAGE_CONFIGURATION.value,
                AccountPermission.VIEW_REGION_DELIVERIES.value,
                AccountPermission.VIEW_PRODUCT_AGGREGATE_REPORT.value,
            },
        )
        self.user.user_permissions.add(*direct_permissions)

        access = access_for(self.user)

        self.assertFalse(access.is_product_manager)
        self.assertEqual(access.product_idents, frozenset({"clc2024"}))
        self.assertTrue(access.can_view_region_deliveries)
        self.assertTrue(access.can_view_product_aggregate_report)
        self.assertTrue(access.can_manage_configuration)
        self.assertFalse(access.can_access_django_admin)
        self.assertTrue(
            access.allows(AccountPermission.MANAGE_CONFIGURATION)
        )

    def test_scoped_permission_requires_nonempty_region_grant(self):
        permission = Permission.objects.get(
            content_type=capability_content_type(),
            codename=AccountPermission.VIEW_REGION_DELIVERIES.value,
        )
        self.user.user_permissions.add(permission)

        access = access_for(self.user)

        self.assertFalse(access.can_view_region_deliveries)

    def test_product_scope_permission_requires_a_product_grant(self):
        self.add_roles(Role.PRODUCT_MANAGER)

        access = access_for(self.user)

        self.assertEqual(access.product_idents, frozenset())
        self.assertFalse(access.can_view_product_deliveries)
        self.assertFalse(access.can_view_product_aggregate_report)

    def test_product_report_access_is_limited_to_the_exact_granted_product(self):
        self.add_roles(Role.PRODUCT_MANAGER)
        UserProductGrant.objects.create(
            user=self.user,
            product_ident="clc2024",
        )

        access = access_for(self.user)

        self.assertTrue(access.can_view_product_report("clc2024"))
        self.assertFalse(access.can_view_product_report("other_product"))
        self.assertFalse(access.can_view_product_report(""))

    def test_administrator_can_view_any_canonical_product_report(self):
        self.add_roles(Role.ADMIN)

        access = access_for(self.user)

        self.assertTrue(access.can_view_product_report("clc2024"))
        self.assertTrue(access.can_view_product_report("another_product"))
        self.assertFalse(access.can_view_product_report(""))

    def test_inactive_user_has_anonymous_access(self):
        self.grant_permissions(AccountPermission.VIEW_REGION_DELIVERIES)
        UserRegionGrant.objects.create(user=self.user, aoi_code="CZ")
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        access = access_for(self.user)

        self.assertFalse(access.is_authenticated)
        self.assertEqual(access.roles, frozenset())
        self.assertFalse(access.can_view_other_users_deliveries)
