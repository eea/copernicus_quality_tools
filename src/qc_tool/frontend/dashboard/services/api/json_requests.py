"""Strict, bounded JSON request parsing shared by QC Tool API views."""

import json

from django.core.exceptions import RequestDataTooBig


class JsonRequestError(Exception):
    """A stable client error that is safe to serialize in an API response."""

    def __init__(self, code, message, status_code=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def read_json_object(request, *, maximum_bytes):
    """Read one UTF-8 JSON object with duplicate-key and size checks."""

    if (
        not isinstance(maximum_bytes, int)
        or isinstance(maximum_bytes, bool)
        or maximum_bytes <= 0
    ):
        raise ValueError("maximum_bytes must be a positive integer")
    content_length = request.META.get("CONTENT_LENGTH")
    if content_length:
        try:
            declared_length = int(content_length)
        except (TypeError, ValueError):
            raise _invalid_json() from None
        if declared_length < 0:
            raise _invalid_json()
        if declared_length > maximum_bytes:
            raise _body_too_large()

    try:
        body = request.body
    except RequestDataTooBig:
        raise _body_too_large() from None
    if len(body) > maximum_bytes:
        raise _body_too_large()
    try:
        value = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_non_finite_number,
        )
    except (
        DuplicateJsonKey,
        RecursionError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
    ):
        raise _invalid_json() from None
    if not isinstance(value, dict):
        raise JsonRequestError(
            "invalid_json_object",
            "The request body must be a JSON object.",
        )
    return value


class DuplicateJsonKey(ValueError):
    pass


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKey
        result[key] = value
    return result


def _reject_non_finite_number(value):
    raise ValueError("non-finite JSON number")


def _invalid_json():
    return JsonRequestError(
        "invalid_json",
        "The request body is not valid JSON.",
    )


def _body_too_large():
    return JsonRequestError(
        "request_body_too_large",
        "The request body exceeds the allowed size.",
        413,
    )
