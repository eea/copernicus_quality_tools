"""API credential generation, storage, and request authentication.

API keys are high-entropy bearer credentials, not passwords. A fast SHA-256
digest is appropriate because the generated secret has 256 bits of entropy.
The raw value is returned only when it is issued and is never stored.
"""

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
import hashlib
import re
import secrets

from django.db.models import Q
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from qc_tool.frontend.accounts.authorization import access_for
from qc_tool.frontend.accounts.models import PersonalAccessToken


API_KEY_PREFIX = "qct_"
API_KEY_ENTROPY_BYTES = 32
API_KEY_TOKEN_LENGTH = 43
API_KEY_LENGTH = len(API_KEY_PREFIX) + API_KEY_TOKEN_LENGTH
API_KEY_DIGEST_PREFIX = "sha256$"
API_KEY_DIGEST_LENGTH = len(API_KEY_DIGEST_PREFIX) + 64
MAX_AUTHORIZATION_HEADER_LENGTH = 128
LAST_USED_WRITE_INTERVAL = timedelta(minutes=5)

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
    token: object | None = None
    access: object | None = None
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
def authenticate_personal_access_token(raw_key):
    """Resolve one active token by exact digest without exposing its secret."""

    if not is_valid_api_key(raw_key):
        return None

    stored_digest = digest_api_key(raw_key)
    token = (
        PersonalAccessToken.objects.select_related("user")
        .filter(secret_digest=stored_digest)
        .first()
    )
    if token is None or not token.user.is_active:
        return None
    return token


def _record_token_use(token):
    """Throttle token activity writes to avoid one database update per call."""

    now = timezone.now()
    cutoff = now - LAST_USED_WRITE_INTERVAL
    updated = PersonalAccessToken.objects.filter(pk=token.pk).filter(
        Q(last_used_at__isnull=True) | Q(last_used_at__lt=cutoff)
    ).update(last_used_at=now)
    if updated:
        token.last_used_at = now


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

    token = authenticate_personal_access_token(raw_key)
    if token is None:
        return ApiKeyAuthenticationResult(error=ApiKeyAuthenticationError.INVALID)

    live_access = access_for(token.user)
    restricted_access = live_access.restricted_to_snapshot(
        permissions=token.permission_snapshot,
        roles=token.role_snapshot,
        product_idents=token.product_idents_snapshot,
        is_administrator=token.is_administrator_snapshot,
    )
    _record_token_use(token)
    return ApiKeyAuthenticationResult(
        user=token.user,
        token=token,
        access=restricted_access,
    )
