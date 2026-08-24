"""Strict parsing for the frontend-to-worker pull-job response.

The worker treats the frontend as a network peer even on a private container
network.  A bounded, explicit projection prevents oversized responses, path
traversal values, duplicate JSON keys, and accidental protocol expansion from
reaching subprocess construction.
"""

import json
import re

from .identifiers import JobIdentifierError
from .identifiers import normalize_job_uuid
from .identifiers import validate_path_component


MAX_PULL_RESPONSE_BYTES = 64 * 1024
_PRODUCT_IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SKIP_STEPS = re.compile(r"[0-9]+(?:,[0-9]+)*\Z")
_REQUIRED_FIELDS = {
    "job_uuid",
    "product_ident",
    "username",
    "filename",
    "skip_steps",
}
_S3_FIELDS = {
    "s3_host",
    "s3_access_key",
    "s3_secret_key",
    "s3_bucketname",
    "s3_key_prefix",
}


class PulledJobError(ValueError):
    """The pull response is unsafe or does not match the worker contract."""


class _DuplicateKey(ValueError):
    pass


def read_pulled_job(response, *, maximum_bytes=MAX_PULL_RESPONSE_BYTES):
    """Return one validated job dictionary, or ``None`` when the queue is empty."""

    if (
        isinstance(maximum_bytes, bool)
        or not isinstance(maximum_bytes, int)
        or maximum_bytes <= 0
    ):
        raise ValueError("maximum_bytes must be a positive integer")

    declared_length = _declared_content_length(response)
    if declared_length is not None and declared_length > maximum_bytes:
        raise PulledJobError("pull response is too large")
    body = response.read(maximum_bytes + 1)
    if not isinstance(body, bytes) or len(body) > maximum_bytes:
        raise PulledJobError("pull response is too large or invalid")
    try:
        payload = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_non_finite,
        )
    except (
        _DuplicateKey,
        RecursionError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
    ):
        raise PulledJobError("pull response is not valid JSON")

    if payload is None:
        return None
    return _validate_job(payload)


def _declared_content_length(response):
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        value = headers.get("Content-Length")
    except AttributeError:
        return None
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise PulledJobError("pull response has an invalid content length")
    if parsed < 0:
        raise PulledJobError("pull response has an invalid content length")
    return parsed


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey
        result[key] = value
    return result


def _reject_non_finite(_value):
    raise ValueError("non-finite JSON number")


def _validate_job(payload):
    if not isinstance(payload, dict):
        raise PulledJobError("pull response must be an object or null")
    fields = set(payload)
    if not _REQUIRED_FIELDS.issubset(fields):
        raise PulledJobError("pull response is missing required fields")
    has_s3 = bool(fields & _S3_FIELDS)
    expected_fields = _REQUIRED_FIELDS | (_S3_FIELDS if has_s3 else set())
    if fields != expected_fields:
        raise PulledJobError("pull response contains unsupported fields")

    try:
        job_uuid = normalize_job_uuid(payload["job_uuid"])
    except JobIdentifierError:
        raise PulledJobError("job UUID is invalid")
    product_ident = _text(payload["product_ident"], 64, ascii_only=True)
    if not _PRODUCT_IDENT.fullmatch(product_ident):
        raise PulledJobError("product identifier is invalid")
    username = _plain_component(payload["username"], 150, "username")
    filename = _plain_component(payload["filename"], 500, "filename")

    skip_steps = payload["skip_steps"]
    if skip_steps is not None:
        skip_steps = _text(skip_steps, 100, ascii_only=True)
        if not _SKIP_STEPS.fullmatch(skip_steps):
            raise PulledJobError("skip steps are invalid")

    result = {
        "job_uuid": job_uuid,
        "product_ident": product_ident,
        "username": username,
        "filename": filename,
        "skip_steps": skip_steps,
    }
    if has_s3:
        result.update(
            {
                "s3_host": _text(payload["s3_host"], 200, ascii_only=True),
                "s3_access_key": _text(
                    payload["s3_access_key"], 100, ascii_only=True
                ),
                "s3_secret_key": _text(
                    payload["s3_secret_key"], 4096, ascii_only=True
                ),
                "s3_bucketname": _text(
                    payload["s3_bucketname"], 100, ascii_only=True
                ),
                "s3_key_prefix": _text(payload["s3_key_prefix"], 500),
            }
        )
    return result


def _text(value, maximum_length, *, ascii_only=False):
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum_length
        or not value.isprintable()
        or (ascii_only and not value.isascii())
    ):
        raise PulledJobError("pull response contains invalid text")
    return value


def _plain_component(value, maximum_length, field_name):
    try:
        return validate_path_component(value, maximum_length, field_name)
    except JobIdentifierError:
        raise PulledJobError("{} is invalid".format(field_name))
