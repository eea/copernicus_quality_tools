"""Orchestrate lookup and presentation for one product page."""

from qc_tool.product_security import canonical_product_ident

from .lookup import current_product_releases
from .presentation import managed_product_detail


def build_product_detail(product_ident, *, include_coverage=False):
    """Return safe product metadata or ``None`` for an unknown identifier."""

    normalized = canonical_product_ident(product_ident)
    if normalized is None:
        return None
    releases, releases_truncated = current_product_releases(normalized)
    if releases:
        return managed_product_detail(
            releases,
            include_coverage=include_coverage,
            releases_truncated=releases_truncated,
        )
    return None
