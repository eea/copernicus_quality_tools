"""Delivery workspace pages."""

from django.conf import settings
from django.shortcuts import render
from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.common import CONFIG
from qc_tool.frontend.dashboard.services.boundaries.presentation import (
    get_boundary_version,
)
from qc_tool.frontend.dashboard.services.configuration.presentation import (
    get_announcement_message,
)
from qc_tool.frontend.dashboard.services.deliveries import (
    count_delivery_statuses,
)

from qc_tool.frontend.dashboard.views.products import (
    _workspace_product_catalog,
)


def deliveries(request):
    """
    Displays the main page with uploaded files and action buttons
    """

    account_access = access_for_request(request)
    delivery_actions_enabled = (
        account_access.can_run_qc
        or account_access.can_delete
        or (
            settings.SUBMISSION_ENABLED
            and account_access.can_submit
        )
    )
    update_job_statuses = CONFIG.get("update_job_statuses", True)
    update_job_statuses_interval = CONFIG.get("update_job_statuses_interval", 30000)
    delivery_status_counts = count_delivery_statuses(account_access)
    product_catalog, product_catalog_available = _workspace_product_catalog()

    context = {
        "submission_enabled": settings.SUBMISSION_ENABLED,
        "announcement": get_announcement_message(),
        "delivery_actions_enabled": delivery_actions_enabled,
        "boundary_version": get_boundary_version(),
        "delivery_status_tabs": delivery_status_counts.as_tabs(),
        "product_catalog": product_catalog,
        "product_catalog_available": product_catalog_available,
        "update_job_statuses": update_job_statuses,
        "update_job_statuses_interval": update_job_statuses_interval,
    }
    return render(request, "dashboard/deliveries/index.html", context)
