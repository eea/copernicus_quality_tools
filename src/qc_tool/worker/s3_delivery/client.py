"""Construction and origin confinement for the S3 client."""

from functools import partial

from botocore.config import Config

from qc_tool.s3_security import InvalidS3Endpoint
from qc_tool.s3_security import require_same_s3_origin

from .errors import rejected_delivery
from .errors import upstream_error


def create_client(endpoint, access_key, secret_key, policy, client_factory):
    """Build a bounded client whose requests cannot change S3 origin."""

    try:
        client = client_factory(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
            config=Config(
                connect_timeout=policy.connect_timeout,
                read_timeout=policy.read_timeout,
                retries={"mode": "standard", "total_max_attempts": 2},
                s3={"addressing_style": "path"},
                inject_host_prefix=False,
                proxies={},
            ),
        )
        client.meta.events.register(
            "before-send.s3",
            partial(_guard_request, endpoint=endpoint),
        )
        return client
    except Exception as exc:
        raise upstream_error("client initialization failed") from exc


def _guard_request(request, *, endpoint, **kwargs):
    try:
        require_same_s3_origin(request.url, endpoint)
    except (AttributeError, InvalidS3Endpoint, TypeError, ValueError) as exc:
        raise rejected_delivery("S3 request changed origin") from exc
