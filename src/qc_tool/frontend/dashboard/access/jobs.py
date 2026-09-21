from django.core.exceptions import PermissionDenied

from qc_tool.frontend.accounts.authorization.permissions import AccountPermission


def can_view_job(account_access, job):
    """Read a job only within its recorded product and ownership scope.

    Rerunning a delivery under another product cannot transfer access to older
    QC artifacts after the original product assignment is revoked.
    """

    if not account_access.allows(AccountPermission.VIEW_DELIVERIES):
        return False
    if account_access.is_administrator:
        return True
    if not (
        account_access.user_id == job.delivery.user_id
        or account_access.can_view_product_deliveries
    ):
        return False
    parent_ident = (
        job.product_release.product.ident if job.product_release_id else None
    )
    return account_access.can_access_product_snapshot(job.product_ident, parent_ident)


def require_job_view(account_access, job):
    if not can_view_job(account_access, job):
        raise PermissionDenied("You are not permitted to view this job.")
    return job
