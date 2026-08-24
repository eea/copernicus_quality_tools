import logging

from django.shortcuts import render


logger = logging.getLogger(__name__)


def permission_denied(request, exception):
    """Render a useful denial without exposing authorization internals."""

    logger.info(
        "Permission denied for user_id=%s path=%s",
        getattr(request.user, "pk", None),
        request.path,
    )
    return render(request, "accounts/errors/403.html", status=403)
