"""Validation of worker status URLs stored by the frontend."""

import ipaddress
from urllib.parse import urlsplit
from uuid import UUID


class InvalidWorkerUrl(ValueError):
    pass


def worker_origin_from_remote_address(remote_address, port):
    """Create a canonical origin from Django's socket peer address."""

    try:
        address = ipaddress.ip_address(remote_address)
    except (TypeError, ValueError) as exc:
        raise InvalidWorkerUrl from exc
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise InvalidWorkerUrl
    host = (
        "[{}]".format(address.compressed)
        if address.version == 6
        else address.compressed
    )
    return "http://{}:{}/".format(host, port)


def worker_job_status_url(worker_url, job_uuid, *, expected_port):
    """Build a status URL only from a canonical IP origin and UUID."""

    try:
        parsed = urlsplit(worker_url)
        port = parsed.port
        address = ipaddress.ip_address(parsed.hostname)
        normalized_uuid = UUID(str(job_uuid))
    except (AttributeError, TypeError, ValueError) as exc:
        raise InvalidWorkerUrl from exc
    if (
        parsed.scheme not in ("http", "https")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or isinstance(expected_port, bool)
        or not isinstance(expected_port, int)
        or not 1 <= expected_port <= 65535
        or port != expected_port
    ):
        raise InvalidWorkerUrl
    host = (
        "[{}]".format(address.compressed)
        if address.version == 6
        else address.compressed
    )
    return "{}://{}:{}/jobs/{}.json".format(
        parsed.scheme,
        host,
        port,
        normalized_uuid,
    )
