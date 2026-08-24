"""Public failures for untrusted archive handling."""


class UnsafeArchiveError(Exception):
    """An archive was invalid, unsafe, or exceeded a configured bound.

    The exception string is intentionally generic. Diagnostic detail remains
    available to trusted logs without being copied into user-facing reports.
    """

    public_message = "The ZIP archive is invalid or exceeds safety limits."

    def __init__(self, detail=None):
        super().__init__(self.public_message)
        self.detail = detail
