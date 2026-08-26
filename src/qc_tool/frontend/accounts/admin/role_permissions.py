from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import PersonalAccessToken
from qc_tool.frontend.accounts.models import UserProfile
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.accounts.models import UserRegionGrant
from qc_tool.frontend.accounts.services.role_permissions import (
    synchronize_role_permissions,
)


MANAGED_MODELS = (
    get_user_model(),
    Group,
    UserProfile,
    PersonalAccessToken,
    UserRegionGrant,
    UserProductGrant,
)
PERMISSION_ACTIONS = ("add", "change", "delete", "view")


def _management_permissions(*, using):
    permissions = []
    content_types = ContentType.objects.db_manager(using)
    permission_manager = Permission.objects.using(using)

    for model in MANAGED_MODELS:
        content_type = content_types.get_for_model(model)
        codenames = [
            f"{action}_{model._meta.model_name}" for action in PERMISSION_ACTIONS
        ]
        permissions.extend(
            permission_manager.filter(
                content_type=content_type,
                codename__in=codenames,
            )
        )

    return permissions


def synchronize_admin_role(*, using="default"):
    """Make the canonical admin group operational and migration-safe.

    Hard-deleting a user would cascade into deliveries and QC history.  User
    lifecycle is therefore managed through ``is_active``; the role keeps CRUD
    access to account-related child records but never receives ``delete_user``.
    """

    with transaction.atomic(using=using):
        synchronize_role_permissions(using=using)
        group, _created = Group.objects.using(using).get_or_create(
            name=Role.ADMIN.value,
        )
        group.permissions.add(*_management_permissions(using=using))

        user_content_type = ContentType.objects.db_manager(using).get_for_model(
            get_user_model()
        )
        delete_user = Permission.objects.using(using).filter(
            content_type=user_content_type,
            codename=f"delete_{get_user_model()._meta.model_name}",
        )
        group.permissions.remove(*delete_user)

        user_model = get_user_model()
        user_model._default_manager.using(using).filter(
            groups__name__in=(Role.ADMIN.value, Role.PRODUCT_MANAGER.value),
        ).update(is_staff=True)

    return group


def synchronize_user_staff(user, *, using=None):
    """Derive admin-site access from operational management roles.

    Product managers enter the admin shell only for explicitly scoped catalog
    and conflict models. They receive no generic Django model permissions.
    """

    if not user.pk:
        return False

    using = using or user._state.db or "default"
    has_staff_role = user.groups.using(using).filter(
        name__in=(Role.ADMIN.value, Role.PRODUCT_MANAGER.value)
    ).exists()
    should_be_staff = bool(user.is_superuser or has_staff_role)

    if user.is_staff != should_be_staff:
        type(user)._default_manager.using(using).filter(pk=user.pk).update(
            is_staff=should_be_staff,
        )
        user.is_staff = should_be_staff

    return should_be_staff
