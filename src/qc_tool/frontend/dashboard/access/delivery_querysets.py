"""Composable ORM selectors for delivery visibility.

Keep list, summary, report, and future dashboard queries on the same access
boundary. Roles are deliberately absent here: effective Django permissions and
explicit scope grants are already resolved into ``AccountAccess``.
"""

from django.db.models import OuterRef, Q, Subquery
from django.db.models.functions import Lower, Trim

from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.dashboard.models import Delivery, Job


def visible_deliveries(account_access):
    """Return active deliveries visible to an authenticated account."""

    # The browser list joins its owner and therefore cannot display orphaned
    # rows. Keep all consumers on that same explicit contract.
    queryset = Delivery.objects.filter(is_deleted=False, user__isnull=False)
    if not (
        account_access.is_authenticated
        and account_access.allows(AccountPermission.VIEW_DELIVERIES)
    ):
        return queryset.none()
    if account_access.is_administrator:
        return queryset

    latest_job = Job.objects.filter(delivery_id=OuterRef("pk")).order_by(
        "-date_created", "-job_uuid",
    )
    queryset = queryset.annotate(
        _scope_product_ident=Lower(Trim("product_ident")),
        _scope_job_id=Subquery(latest_job.values("job_uuid")[:1]),
        _scope_job_product_ident=Lower(Trim(Subquery(
            latest_job.values("product_ident")[:1],
        ))),
        _scope_catalog_ident=Lower(Trim(Subquery(
            latest_job.values("product_release__product__ident")[:1],
        ))),
    )
    unidentified_product = (
        Q(_scope_product_ident__isnull=True) | Q(_scope_product_ident="")
    )
    product_scope = Q(
        _scope_product_ident__in=account_access.product_idents
    ) | Q(
        _scope_catalog_ident__in=account_access.product_idents
    ) | (
        unidentified_product
        & Q(_scope_job_product_ident__in=account_access.product_idents)
    ) | Q(
        _scope_job_id__isnull=True,
        _scope_product_ident__in=account_access.operable_product_idents,
    )
    owner_product_scope = product_scope
    if account_access.product_idents:
        owner_product_scope |= (
            unidentified_product & Q(_scope_job_id__isnull=True)
        )
    visibility = Q(user_id=account_access.user_id) & owner_product_scope
    if account_access.can_view_product_deliveries:
        visibility |= product_scope

    return queryset.filter(visibility).distinct()
