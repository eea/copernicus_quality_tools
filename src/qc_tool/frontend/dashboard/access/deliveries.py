from django.core.exceptions import PermissionDenied

from qc_tool.frontend.accounts.authorization.permissions import AccountPermission


def can_view_delivery(account_access, delivery):
    """Return whether an account may read one delivery and its artifacts."""

    if not account_access.allows(AccountPermission.VIEW_DELIVERIES):
        return False
    if account_access.is_administrator:
        return True
    if (
        account_access.user_id == delivery.user_id
        and delivery_product_scope_matches(account_access, delivery)
    ):
        return True

    return bool(
        account_access.can_view_product_deliveries
        and delivery_product_scope_matches(
            account_access, delivery, allow_unidentified=False,
        )
    )


def delivery_product_scope_matches(account_access, delivery, *, allow_unidentified=True):
    """Match the exact recipe or the latest selected release's catalog product.

    A generic upload has no product until its first QC setup. It remains usable
    by an owner with an assignment; starting QC must separately check the
    selected product. Such uploads never grant cross-owner product visibility.
    """

    if not account_access.is_authenticated:
        return False
    if account_access.is_administrator:
        return True
    if not account_access.product_idents:
        return False
    product_ident = _normalized_product_ident(delivery.product_ident)
    if product_ident in account_access.product_idents:
        return True
    if hasattr(delivery, "_scope_catalog_ident"):
        latest_job = (
            {
                "product_ident": delivery._scope_job_product_ident,
                "product_release__product__ident": delivery._scope_catalog_ident,
            }
            if delivery._scope_job_id else None
        )
    elif getattr(delivery, "pk", None):
        # Keep a catalog-parent grant attached to the selected release; another
        # product may use the same QC definition.
        from qc_tool.frontend.dashboard.models import Job

        latest_job = Job.objects.filter(delivery_id=delivery.pk).order_by(
            "-date_created", "-job_uuid",
        ).values("product_ident", "product_release__product__ident").first()
    else:
        latest_job = None
    if latest_job is None:
        return bool(
            (product_ident is None and allow_unidentified)
            or product_ident in account_access.operable_product_idents
        )
    return account_access.can_access_product_snapshot(
        product_ident or latest_job["product_ident"],
        latest_job["product_release__product__ident"],
    )


def can_manage_delivery(account_access, delivery):
    """Require both ownership and the delivery's assigned product for changes."""

    return bool(
        account_access.can_manage_user(delivery.user_id)
        and delivery_product_scope_matches(account_access, delivery)
    )


def require_delivery_view(account_access, delivery):
    if not can_view_delivery(account_access, delivery):
        raise PermissionDenied("You are not permitted to view this delivery.")
    return delivery


def delivery_action_capabilities(account_access, delivery):
    """Return UI action flags without exposing role policy to the dashboard."""

    can_manage = can_manage_delivery(account_access, delivery)
    return {
        "can_run_qc": can_manage and account_access.can_run_qc,
        "can_delete": can_manage and account_access.can_delete,
        "can_submit": can_manage and account_access.can_submit,
    }


def _normalized_product_ident(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value.casefold() or None
