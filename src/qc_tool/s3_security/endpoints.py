"""Framework-neutral validation for credential-bearing S3 endpoint URLs."""

import ipaddress
import re
from urllib.parse import urlsplit


_DNS_NAME = re.compile(
    r"(?=.{1,253}\Z)"
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z"
)
_NUMERIC_HOST = re.compile(r"[0-9.]+\Z")
_BLOCKED_HOST_SUFFIXES = (
    ".internal",
    ".invalid",
    ".local",
    ".localhost",
    ".test",
    ".home.arpa",
    ".cluster.local",
)


class InvalidS3Endpoint(ValueError):
    """An endpoint is not a canonical public HTTPS origin."""


def canonicalize_s3_endpoint(value):
    """Return a strict public HTTPS origin suitable for ``endpoint_url``."""

    if not isinstance(value, str) or not value or value != value.strip():
        raise InvalidS3Endpoint
    if len(value) > 200 or any(character.isspace() for character in value):
        raise InvalidS3Endpoint
    if "\\" in value or "\x00" in value:
        raise InvalidS3Endpoint

    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise InvalidS3Endpoint from exc

    if parsed.scheme.casefold() != "https":
        raise InvalidS3Endpoint
    if parsed.username is not None or parsed.password is not None:
        raise InvalidS3Endpoint
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise InvalidS3Endpoint

    hostname = parsed.hostname
    if hostname is None:
        raise InvalidS3Endpoint
    try:
        hostname = hostname.encode("ascii").decode("ascii").casefold()
    except UnicodeError as exc:
        raise InvalidS3Endpoint from exc
    if hostname.endswith("."):
        raise InvalidS3Endpoint

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        if _NUMERIC_HOST.fullmatch(hostname) or not _DNS_NAME.fullmatch(hostname):
            raise InvalidS3Endpoint
        if hostname.endswith(_BLOCKED_HOST_SUFFIXES):
            raise InvalidS3Endpoint
        canonical_host = hostname
    else:
        if not address.is_global:
            raise InvalidS3Endpoint
        canonical_host = (
            "[{:s}]".format(address.compressed)
            if address.version == 6
            else address.compressed
        )

    if port is None or port == 443:
        return "https://{:s}".format(canonical_host)
    if not 1 <= port <= 65535:
        raise InvalidS3Endpoint
    return "https://{:s}:{:d}".format(canonical_host, port)


def endpoint_is_allowed(value, allowed_endpoints):
    """Return the canonical endpoint only when it is exactly allowlisted."""

    if not isinstance(allowed_endpoints, (list, tuple, set, frozenset)):
        raise InvalidS3Endpoint
    configured = {
        canonicalize_s3_endpoint(endpoint)
        for endpoint in allowed_endpoints
    }
    if not configured:
        raise InvalidS3Endpoint
    requested = canonicalize_s3_endpoint(value)
    if requested not in configured:
        raise InvalidS3Endpoint
    return requested


def require_same_s3_origin(request_url, expected_endpoint):
    """Reject a credential-bearing request that leaves its approved origin.

    Botocore invokes this check immediately before every S3 request.  It is a
    defence-in-depth guard against redirects, retries, or SDK behaviour that
    would otherwise send credentials to a different host.
    """

    if not isinstance(request_url, str):
        raise InvalidS3Endpoint
    try:
        parsed = urlsplit(request_url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise InvalidS3Endpoint from exc
    if (
        hostname is None
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise InvalidS3Endpoint

    canonical_host = "[{:s}]".format(hostname) if ":" in hostname else hostname
    candidate = "{:s}://{:s}".format(parsed.scheme, canonical_host)
    if port is not None:
        candidate = "{:s}:{:d}".format(candidate, port)
    request_endpoint = canonicalize_s3_endpoint(candidate)
    if request_endpoint != canonicalize_s3_endpoint(expected_endpoint):
        raise InvalidS3Endpoint
    return request_endpoint
