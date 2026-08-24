from enum import Enum

from django.contrib.auth.models import Group


class Role(str, Enum):
    """Canonical application roles backed by Django groups."""

    DEFAULT = "default"
    REGION_MANAGER = "region_manager"
    PRODUCT_MANAGER = "product_manager"
    ADMIN = "admin"

    @classmethod
    def values(cls):
        return tuple(role.value for role in cls)


def roles_for(user):
    """Return recognized roles for a persisted authenticated user."""

    if not getattr(user, "is_authenticated", False) or not getattr(user, "pk", None):
        return frozenset()

    names = user.groups.filter(name__in=Role.values()).values_list(
        "name",
        flat=True,
    )
    return frozenset(Role(name) for name in names)


def ensure_role_groups(*, using="default"):
    """Idempotently expose every supported role in Django Admin."""

    groups = Group.objects.using(using)
    for role in Role:
        groups.get_or_create(name=role.value)
