"""Composable ORM selectors for delivery visibility.

Keep list, summary, report, and future dashboard queries on the same access
boundary. Roles are deliberately absent here: effective Django permissions and
explicit scope grants are already resolved into ``AccountAccess``.
"""

from django.db.models import Q
from django.db.models.functions import Lower

from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.dashboard.models import Delivery


def visible_deliveries(account_access):
    """Return active deliveries visible to an authenticated account."""

    # The browser list joins its owner and therefore cannot display orphaned
    # legacy rows. Keep all consumers on that same explicit contract.
    queryset = Delivery.objects.filter(is_deleted=False, user__isnull=False)
    if not (
        account_access.is_authenticated
        and account_access.allows(AccountPermission.VIEW_DELIVERIES)
    ):
        return queryset.none()
    if account_access.is_administrator:
        return queryset

    visibility = Q(user_id=account_access.user_id)
    if account_access.can_view_region_deliveries:
        visibility |= Q(
            user__userprofile__country__in=account_access.region_codes
        )
    if account_access.can_view_product_deliveries:
        queryset = queryset.annotate(
            _scope_product_ident=Lower("product_ident")
        )
        visibility |= Q(
            _scope_product_ident__in=account_access.product_idents
        )

    return queryset.filter(visibility).distinct()
