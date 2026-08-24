from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db.models.signals import m2m_changed
from django.db.models.signals import post_save

from qc_tool.frontend.accounts.authorization.roles import Role


PROTECTED_REVERSE_USER_IDS = "_accounts_protected_reverse_user_ids"


def connect_user_role_signals(_app_config=None):
    """Connect idempotent invariants after Django's app registry is ready."""

    user_model = get_user_model()
    post_save.connect(
        _ensure_roles_after_save,
        sender=user_model,
        dispatch_uid="accounts.ensure_required_user_roles",
    )
    m2m_changed.connect(
        _preserve_required_roles,
        sender=user_model.groups.through,
        dispatch_uid="accounts.preserve_required_user_roles",
    )


def _ensure_roles_after_save(sender, instance, using, raw=False, **_kwargs):
    if raw:
        return
    _ensure_required_roles(instance, using=using)


def _preserve_required_roles(
    sender,
    instance,
    action,
    reverse,
    model,
    pk_set,
    using,
    **_kwargs,
):
    if not reverse:
        if action in {"post_remove", "post_clear"}:
            _ensure_required_roles(instance, using=using)
        return

    if instance.name not in {Role.DEFAULT.value, Role.ADMIN.value}:
        return

    if action == "pre_clear":
        user_ids = instance.user_set.using(using).values_list("pk", flat=True)
        setattr(instance, PROTECTED_REVERSE_USER_IDS, tuple(user_ids))
        return

    if action == "post_remove":
        user_ids = pk_set or ()
    elif action == "post_clear":
        user_ids = getattr(instance, PROTECTED_REVERSE_USER_IDS, ())
        if hasattr(instance, PROTECTED_REVERSE_USER_IDS):
            delattr(instance, PROTECTED_REVERSE_USER_IDS)
    else:
        return

    users = model._default_manager.using(using).filter(pk__in=user_ids)
    for user in users.iterator(chunk_size=1000):
        _ensure_required_roles(user, using=using)


def _ensure_required_roles(user, *, using):
    role_names = {Role.DEFAULT.value}
    if user.is_superuser:
        role_names.add(Role.ADMIN.value)

    existing_names = set(
        user.groups.using(using).filter(name__in=role_names).values_list(
            "name",
            flat=True,
        )
    )
    groups = [
        Group.objects.using(using).get_or_create(name=name)[0]
        for name in sorted(role_names.difference(existing_names))
    ]
    if groups:
        user.groups.add(*groups)
