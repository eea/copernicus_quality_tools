"""Bounded product catalog lookups."""

from django.db.models import Prefetch

from qc_tool.frontend.dashboard.models import ProductRelease
from qc_tool.frontend.dashboard.models import ProductReleaseDefinition


MAX_CURRENT_RELEASES = 10


def product_release_queryset(product_ident, *, definition_idents=None):
    """Select ordered current plans and only the definitions in the user's scope."""
    definition_links = ProductReleaseDefinition.objects.select_related(
        "qc_definition"
    ).order_by("-is_primary", "pk")
    releases = ProductRelease.objects.filter(
        is_current=True, product__ident=product_ident,
    )
    if definition_idents is not None:
        releases = releases.filter(
            definition_links__qc_definition__product_ident__in=definition_idents,
        ).distinct()
        definition_links = definition_links.filter(
            qc_definition__product_ident__in=definition_idents,
        )
    return (
        releases
        .select_related("product")
        .prefetch_related(
            Prefetch("definition_links", queryset=definition_links)
        )
        .order_by("release_key", "pk")
    )


def current_product_releases(product_ident):
    """Return the first bounded page for non-browser service callers."""

    releases = tuple(product_release_queryset(product_ident)[: MAX_CURRENT_RELEASES + 1])
    return releases[:MAX_CURRENT_RELEASES], len(releases) > MAX_CURRENT_RELEASES
