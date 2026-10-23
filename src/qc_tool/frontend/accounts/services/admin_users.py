"""Protect administrator access while Django Admin changes an account."""

from contextlib import contextmanager

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connections, transaction
from django.db.models import Q

from qc_tool.frontend.accounts.authorization.roles import Role


ADMIN_USER_ADVISORY_LOCK_ID = 0x514341444D494E55
LAST_ADMINISTRATOR_MESSAGE = (
    "Keep at least one active administrator with password sign-in enabled. "
    "Set up another administrator before making this change."
)


@contextmanager
def serialized_admin_user_change(*, using):
    """Serialize validation, account saving and role updates in one transaction.

    Locking only the affected user would allow two administrators to remove
    each other's last remaining access. PostgreSQL uses one transaction lock
    for this administration workflow; SQLite retains its normal write locking.
    """
    with transaction.atomic(using=using):
        connection = connections[using]
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [ADMIN_USER_ADVISORY_LOCK_ID])
        yield


def validate_administrator_retention(
    user, *, is_active=None, is_superuser=None, has_admin_role=None,
    has_usable_password=None,
):
    """Reject removal of the last usable administrator inside the write lock."""
    if not user.pk:
        return
    using = user._state.db or "default"
    current_admin_role = user.groups.using(using).filter(name=Role.ADMIN.value).exists()
    currently_available = (
        user.is_active and user.is_staff and user.has_usable_password()
        and (user.is_superuser or current_admin_role)
    )
    if not currently_available:
        return
    remains_available = (
        (user.is_active if is_active is None else is_active)
        and (user.has_usable_password() if has_usable_password is None else has_usable_password)
        and ((user.is_superuser if is_superuser is None else is_superuser)
             or (current_admin_role if has_admin_role is None else has_admin_role))
    )
    if remains_available:
        return
    alternatives = (
        get_user_model()._default_manager.using(using)
        .filter(is_active=True, is_staff=True)
        .filter(Q(is_superuser=True) | Q(groups__name=Role.ADMIN.value))
        .exclude(pk=user.pk).distinct().only("password")
    )
    if not any(candidate.has_usable_password() for candidate in alternatives):
        raise ValidationError(LAST_ADMINISTRATOR_MESSAGE, code="last_administrator")
