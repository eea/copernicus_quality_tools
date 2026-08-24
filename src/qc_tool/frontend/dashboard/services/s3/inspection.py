import logging
import math
import posixpath
import boto3
from botocore.config import Config
from qc_tool.s3_security import require_same_s3_origin

from .contracts import S3Delivery
from .endpoints import InvalidS3Endpoint
from .errors import configuration_error
from .errors import delivery_ambiguous
from .errors import delivery_not_found
from .errors import listing_limit_exceeded
from .errors import lookup_failed


logger = logging.getLogger(__name__)


class UnsafeS3Request(RuntimeError):
    pass


def _require_same_endpoint(request, *, endpoint, **kwargs):
    """Block boto retries or redirects that change the approved origin."""

    try:
        require_same_s3_origin(request.url, endpoint)
    except (AttributeError, InvalidS3Endpoint, TypeError, ValueError) as exc:
        raise UnsafeS3Request("S3 request target is invalid.") from exc


def inspect_s3_delivery(
    registration,
    *,
    connect_timeout,
    read_timeout,
    maximum_objects,
    client_factory=boto3.client,
):
    """Inspect at most one bounded S3 page and identify one delivery."""

    if (
        not isinstance(maximum_objects, int)
        or isinstance(maximum_objects, bool)
        or not 1 <= maximum_objects <= 1000
    ):
        raise configuration_error()
    for timeout in (connect_timeout, read_timeout):
        if (
            not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise configuration_error()

    try:
        client = client_factory(
            "s3",
            endpoint_url=registration.endpoint,
            aws_access_key_id=registration.access_key,
            aws_secret_access_key=registration.secret_key,
            region_name="us-east-1",
            config=Config(
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
                retries={"mode": "standard", "total_max_attempts": 2},
                s3={"addressing_style": "path"},
                inject_host_prefix=False,
                # Do not let ambient HTTP(S)_PROXY variables redirect a
                # credential-bearing request outside the reviewed endpoint.
                proxies={},
            ),
        )
        client.meta.events.register(
            "before-send.s3",
            lambda request, **kwargs: _require_same_endpoint(
                request,
                endpoint=registration.endpoint,
                **kwargs,
            ),
        )
        response = client.list_objects_v2(
            Bucket=registration.bucket_name,
            Prefix=registration.key_prefix,
            MaxKeys=maximum_objects,
        )
    except Exception as exc:
        logger.warning(
            "S3 delivery lookup failed (%s).",
            type(exc).__name__,
        )
        raise lookup_failed() from exc

    if not isinstance(response, dict):
        raise lookup_failed()
    objects = response.get("Contents") or []
    if not isinstance(objects, list):
        raise lookup_failed()
    if response.get("IsTruncated") or len(objects) > maximum_objects:
        raise listing_limit_exceeded()
    if not objects:
        raise delivery_not_found()

    delivery_names = set()
    total_size = 0
    for item in objects:
        if not isinstance(item, dict):
            raise lookup_failed()
        key = item.get("Key")
        size = item.get("Size")
        if (
            not isinstance(key, str)
            or not key
            or not key.isprintable()
            or "\\" in key
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
        ):
            raise lookup_failed()

        basename = posixpath.basename(key)
        delivery_stem = basename.partition(".")[0]
        if not delivery_stem:
            raise lookup_failed()
        delivery_names.add(
            posixpath.join(posixpath.dirname(key), delivery_stem)
        )
        total_size += size

    if len(delivery_names) != 1:
        raise delivery_ambiguous()
    filename = delivery_names.pop()
    if len(posixpath.basename(filename)) > 500:
        raise lookup_failed()
    return S3Delivery(
        filename=filename,
        size_bytes=total_size,
    )
