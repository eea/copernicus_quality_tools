"""HTTP response policies shared by account-protected views."""

from .cache import prevent_private_response_caching


__all__ = ("prevent_private_response_caching",)
