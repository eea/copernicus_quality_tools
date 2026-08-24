"""Machine-authentication contracts shared by QC Tool services."""

from .headers import build_worker_authorization
from .headers import MAX_WORKER_AUTHORIZATION_HEADER_LENGTH
from .headers import parse_worker_authorization
from .headers import WORKER_AUTHENTICATE_HEADER
from .headers import WORKER_AUTH_SCHEME
from .urls import InvalidWorkerUrl
from .urls import worker_origin_from_remote_address
from .urls import worker_job_status_url


__all__ = (
    "build_worker_authorization",
    "MAX_WORKER_AUTHORIZATION_HEADER_LENGTH",
    "parse_worker_authorization",
    "WORKER_AUTHENTICATE_HEADER",
    "WORKER_AUTH_SCHEME",
    "InvalidWorkerUrl",
    "worker_origin_from_remote_address",
    "worker_job_status_url",
)
