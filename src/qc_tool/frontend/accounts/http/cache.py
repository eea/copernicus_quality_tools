"""Cache controls for responses whose content depends on a Django session."""

from django.utils.cache import patch_vary_headers


def prevent_private_response_caching(response):
    """Mark a session-scoped response as private and non-persistable."""

    response["Cache-Control"] = "private, no-store"
    response["Pragma"] = "no-cache"
    patch_vary_headers(response, ("Cookie",))
    return response
