import logging

from django.contrib import admin
from django.shortcuts import render

from qc_tool.frontend.accounts.http import prevent_private_response_caching
from qc_tool.frontend.admin_site import is_admin_request


logger = logging.getLogger(__name__)


def _error_page(request, status):
    if is_admin_request(request):
        return render(request, "admin/qc_tool_error.html", {
            **admin.site.each_context(request),
            "status_code": status,
            "title": "Access denied" if status == 403 else "Page not found",
        }, status=status)
    return render(request, f"accounts/errors/{status}.html", status=status)


def permission_denied(request, exception):
    """Render a useful denial without exposing authorization internals."""

    logger.info(
        "Permission denied for user_id=%s path=%s",
        getattr(request.user, "pk", None),
        request.path,
    )
    return prevent_private_response_caching(
        _error_page(request, 403)
    )


def page_not_found(request, exception):
    """Render a generic recovery page without exposing lookup details."""

    response = _error_page(request, 404)
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return prevent_private_response_caching(response)
