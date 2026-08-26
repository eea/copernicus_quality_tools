"""Bounded product catalog lookups."""

from django.db.models import Prefetch

from qc_tool.frontend.dashboard.models import ProductRelease
from qc_tool.frontend.dashboard.models import ProductReleaseDefinition


MAX_CURRENT_RELEASES = 10


def current_product_releases(product_ident):
    """Return a bounded, stable page of every current release stream."""

    definition_links = ProductReleaseDefinition.objects.select_related(
        "qc_definition"
    ).order_by("-is_primary", "pk")
    releases = tuple(
        ProductRelease.objects.filter(
            is_current=True,
            product__ident=product_ident,
        )
        .select_related("product")
        .prefetch_related(
            Prefetch("definition_links", queryset=definition_links)
        )
        .order_by("release_key", "pk")[: MAX_CURRENT_RELEASES + 1]
    )
    return releases[:MAX_CURRENT_RELEASES], len(releases) > MAX_CURRENT_RELEASES


def managed_catalog_exists():
    return ProductRelease.objects.filter(is_current=True).exists()
