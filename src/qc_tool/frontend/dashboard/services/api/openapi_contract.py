"""Load the bundled OpenAPI contract with a safe deployment server URL."""

from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings


class ApiDocumentationError(RuntimeError):
    """Raised when the bundled OpenAPI contract cannot be served safely."""


@lru_cache(maxsize=1)
def _bundled_openapi_document():
    contract_path = (
        Path(settings.BASE_DIR)
        / "frontend"
        / "dashboard"
        / "static"
        / "dashboard"
        / "api"
        / "openapi.json"
    )
    try:
        document = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ApiDocumentationError(
            "The bundled OpenAPI document is unavailable."
        ) from error

    if not isinstance(document, dict):
        raise ApiDocumentationError("The OpenAPI document must be an object.")
    if not isinstance(document.get("info"), dict):
        raise ApiDocumentationError("The OpenAPI document has no info object.")
    if not isinstance(document.get("paths"), dict):
        raise ApiDocumentationError("The OpenAPI document has no paths object.")
    return document


def openapi_document(api_url):
    """Return an isolated contract with the configured public API base URL."""

    document = deepcopy(_bundled_openapi_document())
    document["servers"] = [
        {
            "url": _normalized_api_url(api_url),
            "description": "Current QC Tool deployment",
        }
    ]
    return document


def _normalized_api_url(api_url):
    if not isinstance(api_url, str) or not api_url.strip():
        raise ApiDocumentationError("The public API URL is not configured.")
    normalized = api_url.strip().rstrip("/")
    try:
        parsed = urlsplit(normalized)
        parsed.port
    except ValueError:
        raise _invalid_api_url() from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise _invalid_api_url()
    return normalized


def _invalid_api_url():
    return ApiDocumentationError(
        "The public API URL must be an HTTP(S) origin and path without "
        "credentials, a query string, or a fragment."
    )
