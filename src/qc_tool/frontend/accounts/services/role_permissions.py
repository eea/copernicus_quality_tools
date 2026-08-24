from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.accounts.authorization.permissions import (
    ROLE_PERMISSION_GRANTS,
)
from qc_tool.frontend.accounts.authorization.roles import ensure_role_groups
from qc_tool.frontend.accounts.models import AccountCapability


def capability_content_type(*, using="default"):
    return ContentType.objects.db_manager(using).get_for_model(
        AccountCapability,
        for_concrete_model=False,
    )


def capability_permissions(*, using="default"):
    content_type = capability_content_type(using=using)
    return Permission.objects.using(using).filter(
        content_type=content_type,
        codename__in=[permission.value for permission in AccountPermission],
    )


def synchronize_role_permissions(*, using="default"):
    """Synchronize the managed QC subset and preserve unrelated grants."""

    with transaction.atomic(using=using):
        ensure_role_groups(using=using)
        permission_by_codename = {
            permission.codename: permission
            for permission in capability_permissions(using=using)
        }
        expected_codenames = {
            permission.value for permission in AccountPermission
        }
        if permission_by_codename.keys() != expected_codenames:
            return False

        managed_permission_ids = {
            permission.pk for permission in permission_by_codename.values()
        }
        groups = Group.objects.using(using)

        for role, grants in ROLE_PERMISSION_GRANTS.items():
            group, _created = groups.get_or_create(name=role.value)
            desired_permissions = [
                permission_by_codename[permission.value]
                for permission in grants
            ]
            desired_ids = {
                permission.pk for permission in desired_permissions
            }
            stale_permissions = group.permissions.using(using).filter(
                pk__in=managed_permission_ids.difference(desired_ids),
            )
            group.permissions.remove(*stale_permissions)
            group.permissions.add(*desired_permissions)

    return True
