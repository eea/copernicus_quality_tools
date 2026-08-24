"""Safe failures raised while materializing an S3 delivery."""


class S3DownloadError(Exception):
    """A bounded S3 operation failed without exposing credentials."""

    public_message = "The S3 delivery could not be downloaded safely."

    def __init__(self, code, detail=None, public_message=None):
        super().__init__(public_message or self.public_message)
        self.code = code
        self.detail = detail
        self.public_message = public_message or self.public_message


def configuration_error(detail=None):
    return S3DownloadError(
        "s3_configuration_error",
        detail,
        "S3 delivery access is not configured securely.",
    )


def rejected_delivery(detail=None):
    return S3DownloadError("s3_delivery_rejected", detail)


def upstream_error(detail=None):
    return S3DownloadError("s3_upstream_error", detail)
