"""Product catalog browser page."""

import logging

from django.shortcuts import render

from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.accounts.services.products import (
    ProductCatalogUnavailable,
)
from qc_tool.product_security import canonical_product_ident
from qc_tool.frontend.dashboard.services.catalog import (
    list_current_product_coverage,
)


logger = logging.getLogger(__name__)


def render_product_catalog(request, *, fallback_catalog):
    """Render catalog metadata and only authorized aggregate coverage."""

    account_access = access_for_request(request)
    product_catalog = list_current_product_coverage()
    catalog_managed = bool(product_catalog)
    if catalog_managed:
        product_catalog = _scope_coverage(product_catalog, account_access)
        product_catalog_available = True
    else:
        product_catalog, product_catalog_available = fallback_catalog()
    return render(
        request,
        "dashboard/products/index.html",
        {
            "product_catalog": product_catalog,
            "product_catalog_available": product_catalog_available,
            "catalog_managed": catalog_managed,
        },
    )


def workspace_product_catalog(load_descriptions):
    """Return safe display records while keeping failures non-fatal."""

    try:
        descriptions = load_descriptions()
    except ProductCatalogUnavailable:
        logger.warning("The product catalog is unavailable for the workspace UI.")
        return (), False
    return (
        tuple(
            {
                "ident": product_ident,
                "description": description,
                "can_view_coverage": False,
                "expected": None,
                "submitted": None,
                "completion_percentage": None,
            }
            for product_ident, description in sorted(
                descriptions.items(),
                key=lambda item: (str(item[1]).casefold(), item[0]),
            )
            if canonical_product_ident(product_ident) is not None
        ),
        True,
    )


def _scope_coverage(product_catalog, account_access):
    products = {}
    for product in product_catalog:
        if canonical_product_ident(product["ident"]) is None:
            logger.warning(
                "Ignoring managed product with an unroutable identifier: %s",
                product["ident"],
            )
            continue
        can_view = account_access.can_view_product_report(product["ident"])
        release = dict(product)
        release["can_view_coverage"] = can_view
        if not can_view:
            for field in (
                "expected",
                "submitted",
                "conflicts",
                "remaining",
                "completion_percentage",
            ):
                release[field] = None
        record = products.setdefault(
            product["ident"],
            {
                "ident": product["ident"],
                "description": product["description"],
                "can_view_coverage": can_view,
                "releases": [],
            },
        )
        record["releases"].append(release)

    records = []
    for record in products.values():
        releases = tuple(record["releases"])
        product = {
            **record,
            "releases": releases,
            "release_count": len(releases),
        }
        if len(releases) == 1:
            product.update(releases[0])
        product.update(
            _aggregate_coverage(releases, record["can_view_coverage"])
        )
        records.append(product)
    return tuple(records)


def _aggregate_coverage(releases, can_view_coverage):
    """Combine authoritative current release streams into one product row."""

    unavailable = {
        "expected": None,
        "submitted": None,
        "conflicts": None,
        "remaining": None,
        "completion_percentage": None,
    }
    if not can_view_coverage or not releases:
        return unavailable
    if any(
        release.get("expected") is None
        or release.get("submitted") is None
        for release in releases
    ):
        return unavailable

    expected = sum(release["expected"] for release in releases)
    submitted = sum(release["submitted"] for release in releases)
    conflicts = sum(release.get("conflicts") or 0 for release in releases)
    return {
        "expected": expected,
        "submitted": submitted,
        "conflicts": conflicts,
        "remaining": expected - submitted,
        "completion_percentage": (
            round((submitted / expected) * 100, 2) if expected else 0.0
        ),
    }
