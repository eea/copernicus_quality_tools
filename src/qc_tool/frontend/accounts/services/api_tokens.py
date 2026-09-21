"""Issue, list, and delete named personal API tokens."""

from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Optional
import unicodedata

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.db import transaction
from django.views.decorators.debug import sensitive_variables

from qc_tool.frontend.accounts.authentication.api_keys import digest_api_key
from qc_tool.frontend.accounts.authentication.api_keys import generate_api_key
from qc_tool.frontend.accounts.authorization import access_for
from qc_tool.frontend.accounts.models import PersonalAccessToken


logger = logging.getLogger(__name__)

MAX_ACTIVE_API_TOKENS = 20
MAX_TOKEN_NAME_LENGTH = 80

_PERMISSION_LABELS = {
    "view_deliveries": "View deliveries",
    "upload_delivery": "Upload deliveries",
    "run_qc": "Run quality checks",
    "delete_delivery": "Delete deliveries",
    "submit_delivery": "Submit deliveries",
    "change_password": "Change password",
    "manage_own_account": "Manage profile",
    "manage_api_credential": "Manage API tokens",
    "manage_configuration": "Manage configuration",
    "view_product_deliveries": "View assigned products",
    "view_product_aggregate_report": "View product reports",
}
_ROLE_LABELS = {
    "default": "User",
    "product_manager": "Product manager",
    "admin": "Administrator",
}


class ApiTokenIssuanceError(ValueError):
    """A safe, expected token issuance failure."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class IssuedApiToken:
    """One-time secret paired with its stored token record."""

    token: PersonalAccessToken
    raw_token: str


@dataclass(frozen=True)
class ApiTokenPresentation:
    """Secret-free token facts prepared for the account settings template."""

    id: int
    name: str
    token_hint: str
    created_at: datetime
    last_used_at: Optional[datetime]
    permission_snapshot: tuple[str, ...]
    role_snapshot: tuple[str, ...]
    product_idents_snapshot: tuple[str, ...]
    is_administrator_snapshot: bool
    permission_labels: tuple[str, ...]
    role_labels: tuple[str, ...]


def normalize_token_name(value):
    """Return a readable, stable token name or raise a safe error."""

    if not isinstance(value, str):
        raise ApiTokenIssuanceError(
            "invalid_name",
            "Enter a name for this token.",
        )
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not normalized:
        raise ApiTokenIssuanceError(
            "invalid_name",
            "Enter a name for this token.",
        )
    if len(normalized) > MAX_TOKEN_NAME_LENGTH:
        raise ApiTokenIssuanceError(
            "invalid_name",
            "Token names may contain at most 80 characters.",
        )
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise ApiTokenIssuanceError(
            "invalid_name",
            "Token names cannot contain control characters.",
        )
    return normalized


def active_api_tokens(user):
    """Return the current user's tokens without loading stored digests."""

    if not getattr(user, "pk", None):
        return PersonalAccessToken.objects.none()
    return PersonalAccessToken.objects.filter(user=user).defer("secret_digest")


def has_active_api_tokens(user):
    """Return whether the current user owns at least one token."""

    return bool(
        getattr(user, "pk", None)
        and PersonalAccessToken.objects.filter(user=user).exists()
    )


def api_token_presentations(user):
    """Return display-safe token facts without ever loading stored digests."""

    presentations = []
    for token in active_api_tokens(user):
        permission_snapshot = _display_snapshot(token.permission_snapshot)
        role_snapshot = _display_snapshot(token.role_snapshot)
        presentations.append(
            ApiTokenPresentation(
                id=token.pk,
                name=token.name,
                token_hint=token.token_hint,
                created_at=token.created_at,
                last_used_at=token.last_used_at,
                permission_snapshot=permission_snapshot,
                role_snapshot=role_snapshot,
                product_idents_snapshot=_display_snapshot(
                    token.product_idents_snapshot
                ),
                is_administrator_snapshot=token.is_administrator_snapshot,
                permission_labels=tuple(
                    _PERMISSION_LABELS[value]
                    for value in permission_snapshot
                    if value in _PERMISSION_LABELS
                ),
                role_labels=tuple(
                    _ROLE_LABELS[value]
                    for value in role_snapshot
                    if value in _ROLE_LABELS
                ),
            )
        )
    return tuple(presentations)


def _display_snapshot(value):
    """Render malformed historical metadata as empty rather than failing."""

    if not isinstance(value, list) or len(value) > 1_000:
        return ()
    return tuple(
        item
        for item in value[:100]
        if isinstance(item, str) and 0 < len(item) <= 100
    )


@sensitive_variables("raw_token")
def issue_personal_access_token(user, name):
    """Create a named token that snapshots the user's current access."""

    if not getattr(user, "pk", None):
        raise ApiTokenIssuanceError(
            "unsaved_user",
            "API tokens can only be created for a saved account.",
        )
    name = normalize_token_name(name)
    user_model = get_user_model()

    with transaction.atomic():
        locked_user = user_model._default_manager.select_for_update().get(
            pk=user.pk,
        )
        if not locked_user.is_active:
            raise ApiTokenIssuanceError(
                "inactive_user",
                "API tokens cannot be created for an inactive account.",
            )
        tokens = PersonalAccessToken.objects.filter(user=locked_user)
        if tokens.count() >= MAX_ACTIVE_API_TOKENS:
            raise ApiTokenIssuanceError(
                "token_limit",
                "Delete an existing token before creating another one.",
            )
        if tokens.filter(name__iexact=name).exists():
            raise ApiTokenIssuanceError(
                "duplicate_name",
                "Choose a different name; token names must be unique.",
            )

        account_access = access_for(locked_user)
        raw_token = generate_api_key()
        try:
            token = PersonalAccessToken.objects.create(
                user=locked_user,
                name=name,
                secret_digest=digest_api_key(raw_token),
                token_hint="{}…".format(raw_token[:12]),
                permission_snapshot=sorted(
                    permission.value
                    for permission in account_access.permissions
                ),
                role_snapshot=sorted(role.value for role in account_access.roles),
                product_idents_snapshot=sorted(account_access.product_idents),
                is_administrator_snapshot=account_access.is_administrator,
            )
        except IntegrityError as exc:
            # A random digest collision is effectively impossible, while a
            # name race should still become a generic, field-safe response.
            raise ApiTokenIssuanceError(
                "token_conflict",
                "The token could not be created. Choose another name and try again.",
            ) from exc

    logger.info(
        "Personal API token issued user_id=%s token_id=%s",
        user.pk,
        token.pk,
    )
    return IssuedApiToken(token=token, raw_token=raw_token)


def delete_personal_access_token(user, token_id):
    """Delete exactly one token owned by the current user."""

    if not getattr(user, "pk", None):
        return None
    user_model = get_user_model()
    with transaction.atomic():
        locked_user = user_model._default_manager.select_for_update().get(
            pk=user.pk,
        )
        token = PersonalAccessToken.objects.filter(
            pk=token_id,
            user=locked_user,
        ).only("pk", "name").first()
        if token is None:
            return None
        token_name = token.name
        token_pk = token.pk
        token.delete()

    logger.info(
        "Personal API token deleted user_id=%s token_id=%s",
        user.pk,
        token_pk,
    )
    return token_name


__all__ = [
    "ApiTokenIssuanceError",
    "ApiTokenPresentation",
    "IssuedApiToken",
    "MAX_ACTIVE_API_TOKENS",
    "active_api_tokens",
    "api_token_presentations",
    "delete_personal_access_token",
    "has_active_api_tokens",
    "issue_personal_access_token",
    "normalize_token_name",
]
