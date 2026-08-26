"""Workspace overview page."""

from django.conf import settings
from django.shortcuts import render
from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard.services.boundaries.presentation import (
    get_boundary_version,
)
from qc_tool.frontend.dashboard.services.configuration.presentation import (
    get_announcement_message,
)
from qc_tool.frontend.dashboard.services.overview import (
    build_workspace_overview,
)

from qc_tool.frontend.dashboard.views.products import (
    _workspace_product_catalog,
)


def dashboard_home(request):
    """Render an access-scoped overview of the authenticated workspace."""

    account_access = access_for_request(request)
    product_catalog, product_catalog_available = _workspace_product_catalog()
    boundary_version = get_boundary_version()
    dashboard = build_workspace_overview(account_access)
    token_count = (
        request.user.personal_access_tokens.count()
        if account_access.can_manage_api_credential
        else None
    )
    has_dashboard_attention = bool(
        dashboard.summary.qc_failed
        or dashboard.summary.unknown_status
        or (
            account_access.can_run_qc
            and dashboard.summary.not_checked
        )
        or (
            settings.SUBMISSION_ENABLED
            and account_access.can_submit
            and dashboard.summary.ready_to_submit
        )
        or not product_catalog_available
        or boundary_version == "Unavailable"
        or token_count == 0
    )
    return render(
        request,
        "dashboard/overview/index.html",
        {
            "announcement": get_announcement_message(),
            "boundary_version": boundary_version,
            "boundary_version_available": boundary_version != "Unavailable",
            "dashboard": dashboard,
            "has_dashboard_attention": has_dashboard_attention,
            "product_catalog_available": product_catalog_available,
            "product_count": len(product_catalog),
            "submission_enabled": settings.SUBMISSION_ENABLED,
            "token_count": token_count,
        },
    )
