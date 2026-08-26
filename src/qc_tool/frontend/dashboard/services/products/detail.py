"""Orchestrate lookup and presentation for one product page."""

from qc_tool.common import load_product_definition
from qc_tool.frontend.accounts.services.products import (
    available_product_descriptions,
)
from qc_tool.product_security import canonical_product_ident

from .lookup import current_product_releases
from .lookup import managed_catalog_exists
from .presentation import definition_backed_detail
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
    if managed_catalog_exists():
        return None
    return definition_backed_detail(
        normalized,
        load_descriptions=available_product_descriptions,
        load_definition=load_product_definition,
    )
