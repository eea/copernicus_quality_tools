class S3RegistrationError(Exception):
    """A safe, client-facing failure during S3 delivery registration."""

    def __init__(self, code, message, *, status_code=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def invalid_request():
    return S3RegistrationError(
        "invalid_s3_request",
        "The S3 registration request is invalid.",
    )


def endpoint_not_allowed():
    return S3RegistrationError(
        "s3_endpoint_not_allowed",
        "The S3 endpoint is not permitted.",
    )


def configuration_error():
    return S3RegistrationError(
        "s3_configuration_error",
        "S3 delivery registration is not configured.",
        status_code=503,
    )


def lookup_failed():
    return S3RegistrationError(
        "s3_lookup_failed",
        "The configured S3 service could not be queried.",
        status_code=502,
    )


def delivery_not_found():
    return S3RegistrationError(
        "s3_delivery_not_found",
        "No S3 delivery matches the supplied prefix.",
    )


def delivery_ambiguous():
    return S3RegistrationError(
        "s3_delivery_ambiguous",
        "The supplied prefix matches more than one S3 delivery.",
    )


def listing_limit_exceeded():
    return S3RegistrationError(
        "s3_listing_limit_exceeded",
        "The supplied prefix matches too many S3 objects.",
    )
