"""API credential generation, storage, and request authentication.

API keys are high-entropy bearer credentials, not passwords. A fast SHA-256
digest is appropriate because the generated secret has 256 bits of entropy.
The raw value is returned only when it is issued and is never stored.
"""

from dataclasses import dataclass
from enum import Enum
import hashlib
import re
import secrets

from django.contrib.auth import get_user_model
from django.db import transaction
from django.views.decorators.debug import sensitive_variables

from qc_tool.frontend.accounts.models import ApiUser


API_KEY_PREFIX = "qct_"
API_KEY_ENTROPY_BYTES = 32
API_KEY_TOKEN_LENGTH = 43
API_KEY_LENGTH = len(API_KEY_PREFIX) + API_KEY_TOKEN_LENGTH
API_KEY_DIGEST_PREFIX = "sha256$"
API_KEY_DIGEST_LENGTH = len(API_KEY_DIGEST_PREFIX) + 64
MAX_AUTHORIZATION_HEADER_LENGTH = 128

_RAW_API_KEY_PATTERN = re.compile(
    rf"{re.escape(API_KEY_PREFIX)}[A-Za-z0-9_-]{{{API_KEY_TOKEN_LENGTH}}}\Z",
    re.ASCII,
)
_API_KEY_DIGEST_PATTERN = re.compile(
    rf"{re.escape(API_KEY_DIGEST_PREFIX)}[0-9a-f]{{64}}\Z",
    re.ASCII,
)


class ApiKeyAuthenticationError(str, Enum):
    """Stable failure reasons used by the HTTP authentication boundary."""

    MISSING = "missing_credentials"
    QUERY_PARAMETER = "query_parameter_not_allowed"
    MALFORMED = "malformed_credentials"
    INVALID = "invalid_token"


@dataclass(frozen=True)
class ApiKeyAuthenticationResult:
    """The result of authenticating one request without exposing its secret."""

    user: object | None = None
    error: ApiKeyAuthenticationError | None = None

    @property
    def is_authenticated(self):
        return self.user is not None and self.error is None


def generate_api_key():
    """Return a new 256-bit, URL-safe API credential."""

    return API_KEY_PREFIX + secrets.token_urlsafe(API_KEY_ENTROPY_BYTES)


def is_valid_api_key(raw_key):
    """Return whether a value has the exact format issued by this service."""

    return (
        isinstance(raw_key, str)
        and _RAW_API_KEY_PATTERN.fullmatch(raw_key) is not None
    )


@sensitive_variables("raw_key")
def digest_api_key(raw_key):
    """Return the versioned database representation for a raw credential."""

    if not is_valid_api_key(raw_key):
        raise ValueError("API key does not use the supported format")
    digest = hashlib.sha256(raw_key.encode("ascii")).hexdigest()
    return f"{API_KEY_DIGEST_PREFIX}{digest}"


def is_api_key_digest(value):
    """Return whether a stored value is a supported, exact digest."""

    return (
        isinstance(value, str)
        and _API_KEY_DIGEST_PATTERN.fullmatch(value) is not None
    )


@sensitive_variables("raw_key")
def issue_or_rotate_api_key(user):
    """Atomically replace a user's credential and return its raw value once."""

    if user.pk is None:
        raise ValueError("API credentials can only be issued to saved users")

    raw_key = generate_api_key()
    stored_digest = digest_api_key(raw_key)
    user_model = get_user_model()

    # Locking the user row serializes initial issuance as well as rotation. A
    # lock on ApiUser alone cannot protect the case where no credential exists.
    with transaction.atomic():
        locked_user = user_model._default_manager.select_for_update().get(
            pk=user.pk,
        )
        ApiUser.objects.update_or_create(
            user=locked_user,
            defaults={"api_key": stored_digest},
        )

    return raw_key


def revoke_api_key(user):
    """Atomically revoke a user's current credential, if one exists."""

    if user.pk is None:
        return False

    user_model = get_user_model()
    with transaction.atomic():
        locked_user = user_model._default_manager.select_for_update().get(
            pk=user.pk,
        )
        deleted, _details = ApiUser.objects.filter(user=locked_user).delete()
    return deleted > 0


def has_api_key(user):
    """Return whether a user has a credential issued in the current format."""

    if user.pk is None:
        return False
    stored_value = (
        ApiUser.objects.filter(user=user)
        .values_list("api_key", flat=True)
        .first()
    )
    return is_api_key_digest(stored_value)


@sensitive_variables("raw_key")
def authenticate_api_key(raw_key):
    """Resolve one active user by exact digest, failing closed on duplicates."""

    if not is_valid_api_key(raw_key):
        return None

    stored_digest = digest_api_key(raw_key)
    credentials = list(
        ApiUser.objects.select_related("user").filter(api_key=stored_digest)[:2]
    )
    if len(credentials) != 1:
        return None

    user = credentials[0].user
    return user if user.is_active else None


@sensitive_variables("authorization", "raw_key")
def _authorization_api_key(request):
    """Extract one strictly formatted, bounded ASCII Bearer credential."""

    if any(parameter.casefold() == "apikey" for parameter in request.GET):
        return None, ApiKeyAuthenticationError.QUERY_PARAMETER

    authorization = request.headers.get("Authorization")
    if authorization is None:
        return None, ApiKeyAuthenticationError.MISSING
    if not isinstance(authorization, str):
        return None, ApiKeyAuthenticationError.MALFORMED
    if not authorization or len(authorization) > MAX_AUTHORIZATION_HEADER_LENGTH:
        return None, ApiKeyAuthenticationError.MALFORMED
    try:
        authorization.encode("ascii")
    except UnicodeEncodeError:
        return None, ApiKeyAuthenticationError.MALFORMED

    prefix = "Bearer "
    # HTTP authentication scheme names are case-insensitive. The separator
    # and credential remain exact: one ASCII space followed by one token.
    if authorization[: len(prefix)].casefold() != prefix.casefold():
        return None, ApiKeyAuthenticationError.MALFORMED
    raw_key = authorization[len(prefix) :]
    if not is_valid_api_key(raw_key):
        return None, ApiKeyAuthenticationError.MALFORMED
    return raw_key, None


@sensitive_variables("raw_key")
def authenticate_api_request(request):
    """Authenticate only the ``Authorization: Bearer`` request contract."""

    raw_key, error = _authorization_api_key(request)
    if error is not None:
        return ApiKeyAuthenticationResult(error=error)

    user = authenticate_api_key(raw_key)
    if user is None:
        return ApiKeyAuthenticationResult(error=ApiKeyAuthenticationError.INVALID)
    return ApiKeyAuthenticationResult(user=user)
