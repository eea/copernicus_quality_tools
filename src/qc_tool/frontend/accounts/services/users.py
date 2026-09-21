from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction

from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.services.product_grants import (
    create_product_grant,
)


@dataclass(frozen=True)
class ProvisionedUser:
    user: object
    created: bool


@transaction.atomic
def provision_user(
    *,
    username,
    password,
    email=None,
    product_idents=(),
    groups=(),
    is_superuser=False,
):
    """Create an account with canonical roles and validated product assignments."""

    user_model = get_user_model()
    username_field = user_model.USERNAME_FIELD
    lookup = {username_field: username}
    existing = user_model._default_manager.filter(**lookup).first()
    if existing is not None:
        return ProvisionedUser(existing, created=False)

    roles = {Role.DEFAULT, *(Role(group) for group in groups)}
    if is_superuser:
        roles.add(Role.ADMIN)
    attributes = dict(lookup)
    email_field = user_model.get_email_field_name()
    if email_field != username_field:
        attributes[email_field] = email or f"{username}@{username}.com"

    creator = (
        user_model._default_manager.create_superuser
        if is_superuser
        else user_model._default_manager.create_user
    )
    user = creator(password=password, **attributes)

    for role in sorted(roles, key=lambda item: item.value):
        group, _created = Group.objects.get_or_create(name=role.value)
        user.groups.add(group)

    for product_ident in dict.fromkeys(product_idents):
        create_product_grant(user=user, product_ident=product_ident)

    return ProvisionedUser(user, created=True)
