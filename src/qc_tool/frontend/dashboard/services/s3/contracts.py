from dataclasses import dataclass
import ipaddress
import re

from .endpoints import require_allowed_s3_endpoint
from .errors import invalid_request


_BUCKET_NAME = re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]\Z")


@dataclass(frozen=True)
class S3Registration:
    endpoint: str
    access_key: str
    secret_key: str
    bucket_name: str
    key_prefix: str


@dataclass(frozen=True)
class S3Delivery:
    filename: str
    size_bytes: int


def _required_text(payload, name, *, maximum_length, ascii_only=False):
    value = payload.get(name)
    if not isinstance(value, str) or not value or value != value.strip():
        raise invalid_request()
    if len(value) > maximum_length or not value.isprintable():
        raise invalid_request()
    if ascii_only and not value.isascii():
        raise invalid_request()
    return value


def parse_s3_registration(payload, *, allowed_endpoints):
    if not isinstance(payload, dict):
        raise invalid_request()

    endpoint = require_allowed_s3_endpoint(
        payload.get("host"),
        allowed_endpoints,
    )
    access_key = _required_text(
        payload,
        "access_key",
        maximum_length=100,
        ascii_only=True,
    )
    secret_key = _required_text(
        payload,
        "secret_key",
        maximum_length=100,
        ascii_only=True,
    )
    bucket_name = _required_text(
        payload,
        "bucketname",
        maximum_length=63,
        ascii_only=True,
    )
    key_prefix = _required_text(payload, "key_prefix", maximum_length=500)

    if (
        not _BUCKET_NAME.fullmatch(bucket_name)
        or ".." in bucket_name
        or ".-" in bucket_name
        or "-." in bucket_name
    ):
        raise invalid_request()
    try:
        ipaddress.ip_address(bucket_name)
    except ValueError:
        pass
    else:
        raise invalid_request()
    if "\\" in key_prefix:
        raise invalid_request()

    return S3Registration(
        endpoint=endpoint,
        access_key=access_key,
        secret_key=secret_key,
        bucket_name=bucket_name,
        key_prefix=key_prefix,
    )
