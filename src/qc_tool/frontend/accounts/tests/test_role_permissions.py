from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.test import TestCase

from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.accounts.authorization.permissions import (
    ROLE_PERMISSION_GRANTS,
)
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import AccountCapability
from qc_tool.frontend.accounts.services.role_permissions import (
    capability_content_type,
)
from qc_tool.frontend.accounts.services.role_permissions import (
    synchronize_role_permissions,
)


class AccountCapabilityModelTests(TestCase):
    def test_unmanaged_anchor_declares_only_qc_capabilities(self):
        declared_codenames = {
            codename for codename, _label in AccountCapability._meta.permissions
        }

        self.assertFalse(AccountCapability._meta.managed)
        self.assertEqual(AccountCapability._meta.default_permissions, ())
        self.assertEqual(
            declared_codenames,
            {permission.value for permission in AccountPermission},
        )

    def test_django_created_every_capability_permission(self):
        codenames = set(
            Permission.objects.filter(
                content_type=capability_content_type(),
            ).values_list("codename", flat=True)
        )

        self.assertEqual(
            codenames,
            {permission.value for permission in AccountPermission},
        )


class RolePermissionSynchronizationTests(TestCase):
    def capability_codenames(self, role):
        return set(
            Group.objects.get(name=role.value)
            .permissions.filter(content_type=capability_content_type())
            .values_list("codename", flat=True)
        )

    def test_each_role_has_its_exact_capability_bundle(self):
        for role, permissions in ROLE_PERMISSION_GRANTS.items():
            with self.subTest(role=role):
                self.assertEqual(
                    self.capability_codenames(role),
                    {permission.value for permission in permissions},
                )

    def test_sync_is_idempotent_and_preserves_unrelated_permissions(self):
        product_group = Group.objects.get(name=Role.PRODUCT_MANAGER.value)
        unrelated_permission = Permission.objects.exclude(
            content_type=capability_content_type(),
        ).first()
        stale_capability = Permission.objects.get(
            content_type=capability_content_type(),
            codename=AccountPermission.UPLOAD_DELIVERY.value,
        )
        product_group.permissions.add(
            unrelated_permission,
            stale_capability,
        )

        self.assertTrue(synchronize_role_permissions())
        self.assertTrue(synchronize_role_permissions())

        self.assertEqual(
            self.capability_codenames(Role.PRODUCT_MANAGER),
            {
                permission.value
                for permission in ROLE_PERMISSION_GRANTS[Role.PRODUCT_MANAGER]
            },
        )
        self.assertTrue(
            product_group.permissions.filter(pk=unrelated_permission.pk).exists()
        )

    def test_sync_does_not_recreate_the_retired_region_role(self):
        self.assertFalse(Group.objects.filter(name="region_manager").exists())

        self.assertTrue(synchronize_role_permissions())

        self.assertFalse(Group.objects.filter(name="region_manager").exists())
