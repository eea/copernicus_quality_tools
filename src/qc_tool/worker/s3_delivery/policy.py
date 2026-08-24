"""Environment-driven resource and network policy for worker S3 access."""

from dataclasses import dataclass
import math
import os

from qc_tool.archive_security import ArchiveLimits
from qc_tool.s3_security import endpoint_is_allowed
from qc_tool.s3_security import InvalidS3Endpoint

from .errors import configuration_error


@dataclass(frozen=True)
class S3DownloadPolicy:
    """Reviewed bounds used for both listing and streaming objects."""

    allowed_endpoints: tuple
    connect_timeout: float = 3.0
    read_timeout: float = 30.0
    max_objects: int = 1000
    max_download_bytes: int = 50 * 1024 * 1024 * 1024

    def __post_init__(self):
        if not isinstance(self.allowed_endpoints, tuple):
            raise ValueError("allowed_endpoints must be a tuple")
        if (
            isinstance(self.max_objects, bool)
            or not isinstance(self.max_objects, int)
            or not 1 <= self.max_objects <= 1000
        ):
            raise ValueError("max_objects must be between 1 and 1000")
        if (
            isinstance(self.max_download_bytes, bool)
            or not isinstance(self.max_download_bytes, int)
            or self.max_download_bytes <= 0
        ):
            raise ValueError("max_download_bytes must be positive")
        for timeout in (self.connect_timeout, self.read_timeout):
            if (
                isinstance(timeout, bool)
                or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout)
                or timeout <= 0
            ):
                raise ValueError("S3 timeouts must be finite and positive")

    @classmethod
    def from_environment(cls):
        raw_endpoints = os.environ.get("S3_ALLOWED_ENDPOINTS", "")
        endpoints = _endpoint_list(raw_endpoints)
        try:
            return cls(
                allowed_endpoints=endpoints,
                connect_timeout=_positive_float(
                    "S3_CONNECT_TIMEOUT_SECONDS",
                    3.0,
                ),
                read_timeout=_positive_float(
                    "S3_READ_TIMEOUT_SECONDS",
                    30.0,
                ),
                max_objects=_bounded_integer(
                    "S3_MAX_LISTED_OBJECTS",
                    1000,
                    maximum=1000,
                ),
                max_download_bytes=_bounded_integer(
                    "S3_MAX_DOWNLOAD_BYTES",
                    ArchiveLimits().max_archive_bytes,
                ),
            )
        except (TypeError, ValueError) as exc:
            raise configuration_error(type(exc).__name__) from exc

    def authorize(self, endpoint):
        """Return one canonical endpoint or fail closed."""

        try:
            return endpoint_is_allowed(endpoint, self.allowed_endpoints)
        except (InvalidS3Endpoint, TypeError) as exc:
            raise configuration_error("endpoint is not allowlisted") from exc


def _endpoint_list(raw_value):
    if not isinstance(raw_value, str):
        raise ValueError("S3_ALLOWED_ENDPOINTS must be text")
    if not raw_value:
        return tuple()
    parts = raw_value.split(",")
    if any(not part or part != part.strip() for part in parts):
        raise ValueError("S3_ALLOWED_ENDPOINTS is malformed")
    return tuple(parts)


def _positive_float(name, default):
    raw_value = os.environ.get(name)
    value = default if raw_value is None else float(raw_value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("{} must be finite and positive".format(name))
    return value


def _bounded_integer(name, default, maximum=None):
    raw_value = os.environ.get(name)
    value = default if raw_value is None else int(raw_value)
    if value <= 0 or (maximum is not None and value > maximum):
        raise ValueError("{} is outside its allowed range".format(name))
    return value
