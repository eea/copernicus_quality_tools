"""Shared Authorization-header contract for frontend/worker communication."""


WORKER_AUTH_SCHEME = "WorkerToken"
WORKER_AUTHENTICATE_HEADER = 'WorkerToken realm="QC Tool Worker"'
MAX_WORKER_AUTHORIZATION_HEADER_LENGTH = 256


def build_worker_authorization(token):
    """Build one strict header without accepting control characters."""

    if not _safe_token(token):
        raise ValueError("worker token is invalid")
    return "{} {}".format(WORKER_AUTH_SCHEME, token)


def parse_worker_authorization(value):
    """Return a token only for ``Authorization: WorkerToken <token>``."""

    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_WORKER_AUTHORIZATION_HEADER_LENGTH
    ):
        return None
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        return None
    if value.count(" ") != 1:
        return None
    scheme, token = value.split(" ", 1)
    if scheme.casefold() != WORKER_AUTH_SCHEME.casefold() or not _safe_token(token):
        return None
    return token


def _safe_token(value):
    if not isinstance(value, str) or not value or len(value) > 200:
        return False
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        return False
    return value.isprintable() and not any(character.isspace() for character in value)
