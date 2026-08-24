from django.contrib.auth import get_user_model
from django.db.models.signals import m2m_changed
from django.db.models.signals import post_migrate

from qc_tool.frontend.accounts.admin.role_permissions import synchronize_admin_role
from qc_tool.frontend.accounts.admin.role_permissions import synchronize_user_staff
from qc_tool.frontend.accounts.authorization.roles import Role


def _after_migrate(sender, using, **kwargs):
    synchronize_admin_role(using=using)


def _admin_membership_changed(
    sender,
    instance,
    action,
    reverse,
    model,
    pk_set,
    using,
    **kwargs,
):
    if reverse:
        _synchronize_group_members(instance, action, pk_set, using)
    elif action in {"post_add", "post_remove", "post_clear"}:
        synchronize_user_staff(instance, using=using)


def _synchronize_group_members(group, action, pk_set, using):
    if group.name != Role.ADMIN.value:
        return

    user_model = get_user_model()
    if action == "pre_clear":
        group._admin_member_ids_before_clear = tuple(
            group.user_set.using(using).values_list("pk", flat=True)
        )
        return

    user_ids = pk_set
    if action == "post_clear":
        user_ids = getattr(group, "_admin_member_ids_before_clear", ())
        if hasattr(group, "_admin_member_ids_before_clear"):
            del group._admin_member_ids_before_clear

    if action == "post_add":
        user_model._default_manager.using(using).filter(pk__in=user_ids).update(
            is_staff=True,
        )
    elif action in {"post_remove", "post_clear"}:
        user_model._default_manager.using(using).filter(
            pk__in=user_ids,
            is_superuser=False,
        ).update(is_staff=False)
        user_model._default_manager.using(using).filter(
            pk__in=user_ids,
            is_superuser=True,
        ).update(is_staff=True)


def connect_account_admin_signals(_app_config):
    """Connect account lifecycle hooks once during app initialization."""

    post_migrate.connect(
        _after_migrate,
        weak=False,
        dispatch_uid="accounts.synchronize_admin_role",
    )
    m2m_changed.connect(
        _admin_membership_changed,
        sender=get_user_model().groups.through,
        weak=False,
        dispatch_uid="accounts.synchronize_admin_membership",
    )
