"""Identify the authenticated maintenance controls through URL ownership."""

from django.urls import Resolver404
from django.urls import resolve


CONTROL_ROUTE_NAMES = frozenset({"admin_maintenance", "worker_maintenance", "admin_data_transfer",
                               "admin_data_transfer_status", "admin_data_transfer_download",
                               "admin_data_transfer_no_slash", "admin_data_transfer_legacy", "admin_storage_action",
                               "admin_data_transfer_status_legacy", "admin_data_transfer_download_legacy"})
# These POST endpoints inspect/convert data. Their handlers explicitly avoid
# incidental refresh writes while maintenance is active.
READ_POST_ROUTE_NAMES = frozenset({"table_export", "update_job", "delivery_upload_check"})
# A resumable GET probe creates registration locks on shared storage.
WRITE_ROUTE_NAMES = frozenset({"resumable_upload", "pull_job"})
LOGIN_ROUTE_NAMES = frozenset({"login", "admin_login"})


def _route_name(request):
    try:
        return resolve(request.path_info, urlconf=getattr(request, "urlconf", None)).url_name
    except Resolver404:
        return None


def is_maintenance_control_request(request):
    """Respect deployment prefixes and request-specific URL configurations."""

    return _route_name(request) in CONTROL_ROUTE_NAMES


def is_maintenance_read_request(request):
    """Classify effects, preserving read POSTs and rejecting write GETs."""
    name = _route_name(request)
    if name in WRITE_ROUTE_NAMES:
        return False
    return request.method in {"GET", "HEAD", "OPTIONS"} or (
        request.method == "POST" and name in READ_POST_ROUTE_NAMES
    )


def is_maintenance_login_request(request):
    return request.method in {"GET", "HEAD", "POST"} and _route_name(request) in LOGIN_ROUTE_NAMES
