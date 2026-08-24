from django.core.exceptions import PermissionDenied

from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.dashboard.access.legacy_regions import (
    legacy_delivery_region_code,
)


def can_view_delivery(account_access, delivery):
    """Return whether an account may read one delivery and its artifacts."""

    if not account_access.allows(AccountPermission.VIEW_DELIVERIES):
        return False
    if account_access.is_administrator:
        return True
    if account_access.user_id == delivery.user_id:
        return True

    if _region_scope_matches(account_access, delivery):
        return True

    return bool(
        account_access.can_view_product_deliveries
        and _normalized_product_ident(delivery.product_ident)
        in account_access.product_idents
    )


def require_delivery_view(account_access, delivery):
    if not can_view_delivery(account_access, delivery):
        raise PermissionDenied("You are not permitted to view this delivery.")
    return delivery


def delivery_action_capabilities(account_access, owner_id):
    """Return UI action flags without exposing role policy to the dashboard."""

    can_manage = account_access.can_manage_user(owner_id)
    return {
        "can_run_qc": can_manage and account_access.can_run_qc,
        "can_delete": can_manage and account_access.can_delete,
        "can_submit": can_manage and account_access.can_submit,
    }


def _region_scope_matches(account_access, delivery):
    if not account_access.can_view_region_deliveries:
        return False
    return legacy_delivery_region_code(delivery) in account_access.region_codes


def _normalized_product_ident(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value.casefold() or None
