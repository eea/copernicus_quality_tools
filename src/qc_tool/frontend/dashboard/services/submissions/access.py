"""Submission receipt visibility, independent of delivery browsing grants."""

from django.db.models import Count, Q
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
        "delivery__user", "job", "product_release__product", "product_unit",
    )
    if not access.is_authenticated:
        return queryset.none()
    if access.is_administrator:
        return queryset
    if not access.product_idents:
        # Keep an empty SQL subquery rather than an EmptyResultSet. Receipt
        # scopes are used in negated aggregate delivery filters;
        # compiler-empty IN clauses can short-circuit all counts.
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


def reviewable_submissions(access):
    """Keep the review queue within the user's decision-making scope."""

    queryset = visible_submissions(access)
    if not access.can_view_submission_queue:
        return queryset.none()
    if access.is_administrator:
        return queryset
    return queryset.filter(
        product_release__product__ident__in=access.reviewable_product_idents,
    )


def awaiting_review_submissions(access):
    """Published candidates needing a decision, shared by queues and badges."""

    return reviewable_submissions(access).filter(
        publication_state=DeliverySubmission.PublicationState.PUBLISHED,
        review_state__in=(
            DeliverySubmission.ReviewState.PENDING,
            DeliverySubmission.ReviewState.CONFLICT,
        ),
    )


def pending_review_counts(access, *, product_idents):
    """Count candidates by catalog product in one permission-scoped query."""

    return dict(
        awaiting_review_submissions(access)
        .filter(product_release__product__ident__in=product_idents)
        .order_by()
        .values("product_release__product__ident")
        .annotate(pending_count=Count("pk"))
        .values_list("product_release__product__ident", "pending_count")
    )
