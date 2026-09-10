"""Submission receipt visibility, independent of delivery browsing grants."""

from django.db.models import Q

from qc_tool.frontend.dashboard.models import DeliverySubmission


def can_view_submission(access, *, owner_id, product_ident):
    """Owners and authorized reviewers may read retained review feedback."""

    return access.is_authenticated and (
        access.user_id == owner_id
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
    scope = Q(delivery__user_id=access.user_id)
    if access.is_product_manager:
        scope |= Q(product_release__product__ident__in=access.reviewable_product_idents)
    return queryset.filter(scope)
