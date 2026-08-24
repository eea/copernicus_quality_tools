from qc_tool.s3_security import canonicalize_s3_endpoint
from qc_tool.s3_security import endpoint_is_allowed
from qc_tool.s3_security import InvalidS3Endpoint

from .errors import configuration_error
from .errors import endpoint_not_allowed


def require_allowed_s3_endpoint(value, allowed_endpoints):
    """Validate the configured allowlist and authorize one exact origin."""

    if not isinstance(allowed_endpoints, (list, tuple, set, frozenset)):
        raise configuration_error()
    if not allowed_endpoints:
        raise configuration_error()

    try:
        return endpoint_is_allowed(value, allowed_endpoints)
    except (InvalidS3Endpoint, TypeError):
        try:
            canonicalize_s3_endpoint(value)
        except (InvalidS3Endpoint, TypeError):
            raise endpoint_not_allowed()
        # A malformed allowlist is an operator error; a valid but absent
        # requested endpoint is an authorization denial.
        try:
            for endpoint in allowed_endpoints:
                canonicalize_s3_endpoint(endpoint)
        except (InvalidS3Endpoint, TypeError):
            raise configuration_error()
        if not allowed_endpoints:
            raise configuration_error()
        raise endpoint_not_allowed()
