"""Submission receipt visibility, independent of delivery browsing grants."""

from django.db.models import Q
from django.db.models.functions import Lower, Trim

from qc_tool.frontend.dashboard.models import DeliverySubmission


def can_view_submission(access, *, owner_id, product_ident, recipe_ident=None):
    """Assigned owners and authorized reviewers may read retained evidence."""

    return access.is_authenticated and (
        (
            access.user_id == owner_id
            and access.can_access_product_snapshot(recipe_ident, product_ident)
        )
        or access.can_review_product_submission(product_ident)
    )


def visible_submissions(access):
    queryset = DeliverySubmission.objects.select_related(
        "delivery__user", "job", "product_release__product", "product_aoi",
    )
    if not access.is_authenticated:
        return queryset.none()
    if access.is_administrator:
        return queryset
    if not access.product_idents:
        # Keep an empty SQL subquery rather than an EmptyResultSet. Receipt
        # scopes are used in negated aggregate filters for region-visible
        # deliveries; compiler-empty IN clauses can short-circuit all counts.
        return queryset.filter(pk__isnull=True)
    queryset = queryset.annotate(
        _scope_recipe_ident=Lower(Trim("job__product_ident")),
        _scope_product_ident=Lower(Trim("product_release__product__ident")),
    )
    owner_products = Q(_scope_recipe_ident__in=access.product_idents) | Q(
        _scope_product_ident__in=access.product_idents,
    )
    scope = Q(delivery__user_id=access.user_id) & owner_products
    if access.is_product_manager:
        scope |= Q(product_release__product__ident__in=access.reviewable_product_idents)
    return queryset.filter(scope)
