import logging

from django.shortcuts import render

from qc_tool.frontend.accounts.http import prevent_private_response_caching


logger = logging.getLogger(__name__)


def permission_denied(request, exception):
    """Render a useful denial without exposing authorization internals."""

    logger.info(
        "Permission denied for user_id=%s path=%s",
        getattr(request.user, "pk", None),
        request.path,
    )
    return prevent_private_response_caching(
        render(request, "accounts/errors/403.html", status=403)
    )
