from qc_tool.frontend.dashboard.access.deliveries import can_view_delivery
from qc_tool.frontend.dashboard.access.deliveries import require_delivery_view


def can_view_job(account_access, job):
    """Jobs inherit the access policy of their delivery."""

    return can_view_delivery(account_access, job.delivery)


def require_job_view(account_access, job):
    require_delivery_view(account_access, job.delivery)
    return job
