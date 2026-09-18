"""Product catalog browser page."""

import logging

from django.shortcuts import render
from django.urls import reverse

from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.accounts.services.products import (
    ProductCatalogUnavailable,
)
from qc_tool.product_security import canonical_product_ident
from qc_tool.frontend.dashboard.services.catalog import (
    list_current_product_coverage,
)
from qc_tool.frontend.dashboard.models import Product
from qc_tool.frontend.dashboard.services.catalog.readiness import product_readiness_many


logger = logging.getLogger(__name__)


def render_product_catalog(request):
    """Render catalog metadata and only authorized aggregate coverage."""

    account_access = access_for_request(request)
    show_archived = account_access.is_administrator and request.GET.get("archived") == "1"
    product_catalog = list_current_product_coverage(include_inactive=show_archived)
    if show_archived:
        product_catalog = tuple(row for row in product_catalog if not row["is_active"])
    product_catalog = _scope_coverage(product_catalog, account_access)
    product_catalog = tuple(
        {**product, **_plan_presentation(product, managed=True)}
        for product in product_catalog
        if account_access.can_browse_product(product["ident"])
    )
    visible_products = Product.objects.filter(ident__in=(
        product["ident"] for product in product_catalog if product["can_view_coverage"]
    ))
    visible_products = tuple(visible_products)
    readiness_by_id = product_readiness_many(visible_products)
    readiness_by_ident = {
        product.ident: readiness_by_id[product.pk] for product in visible_products
    }
    product_catalog = tuple(
        {**product, "readiness": readiness_by_ident.get(product["ident"])}
        for product in product_catalog
    )
    plan_filters = tuple(
        {"value": status, "label": label, "count": count}
        for status, label in (
            ("approved", "Approved"),
            ("draft", "Draft"),
            ("undefined", "Not defined"),
            ("mixed", "Mixed plans"),
            ("retired", "Retired"),
            ("restricted", "Restricted"),
        )
        if (count := sum(product["plan_status"] == status for product in product_catalog))
    )
    return render(
        request,
        "dashboard/products/index.html",
        {
            "product_catalog": product_catalog,
            "product_catalog_available": True,
            "catalog_managed": True,
            "show_archived": show_archived,
            "catalog_tabs": (
                {"label": "Active products", "url": reverse("products"), "active": not show_archived},
                {"label": "Removed products", "url": reverse("products") + "?archived=1", "active": show_archived},
            ),
            "product_count": len(product_catalog),
            "plan_filters": plan_filters,
        },
    )


def _plan_presentation(product, *, managed):
    """Explain scoped coverage without exposing hidden release plan states."""

    if managed and not product["can_view_coverage"]:
        status = "restricted"
    elif product.get("expected") is not None:
        status = "approved"
    else:
        states = {
            release["coverage_state"] for release in product.get("releases", ())
        }
        status = {
            frozenset({"draft"}): "draft",
            frozenset({"unknown"}): "undefined",
            frozenset({"retired"}): "retired",
            frozenset(): "undefined",
        }.get(frozenset(states), "mixed")

    presentation = {
        "approved": (
            "Approved",
            "The required product units are approved for delivery.",
            "Approved scope",
            (
                "Accepted submissions against the approved plan"
                if product.get("expected")
                else "No product units in the approved plan"
            ),
        ),
        "draft": (
            "Draft",
            "The declared delivery scope still needs approval.",
            "Provisional scope",
            "Awaiting plan approval",
        ),
        "undefined": (
            "Not defined",
            "An expected delivery scope has not been defined.",
            "product units not specified",
            "Define expected product units",
        ),
        "mixed": (
            "Mixed plans",
            "The release plans have different approval states.",
            (
                "Includes unapproved scope"
                if product.get("declared_expected") is not None
                else "Full scope unavailable"
            ),
            "Review release plans",
        ),
        "retired": (
            "Retired",
            "All delivery plans for this product are retired.",
            "Plan retired",
            "Plan retired",
        ),
        "restricted": (
            "Restricted",
            "You do not have access to this product's delivery coverage.",
            "Coverage restricted",
            "Coverage restricted",
        ),
    }
    label, hint, expected_hint, progress_hint = presentation[status]
    return {
        "plan_status": status,
        "plan_label": label,
        "plan_hint": hint,
        "expected_hint": expected_hint,
        "progress_hint": progress_hint,
    }


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
                "declared_expected": None,
                "expected": None,
                "accepted": None,
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
                "declared_expected",
                "expected",
                "accepted",
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
                "is_active": product.get("is_active", True),
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
            "scope_is_draft": record["can_view_coverage"] and any(
                release["coverage_state"] == "draft"
                for release in releases
            ),
        }
        if len(releases) == 1:
            product.update(releases[0])
        product.update(
            _aggregate_coverage(releases, record["can_view_coverage"])
        )
        records.append(product)
    return tuple(records)


def _aggregate_coverage(releases, can_view_coverage):
    """Total declared scope separately from authoritative delivery progress."""

    unavailable = {
        "declared_expected": None,
        "expected": None,
        "accepted": None,
        "conflicts": None,
        "remaining": None,
        "completion_percentage": None,
    }
    if not can_view_coverage or not releases:
        return unavailable
    if all(release.get("declared_expected") is not None for release in releases):
        unavailable["declared_expected"] = sum(
            release["declared_expected"] for release in releases
        )
    if any(
        release.get("expected") is None
        or release.get("accepted") is None
        for release in releases
    ):
        return unavailable

    expected = sum(release["expected"] for release in releases)
    accepted = sum(release["accepted"] for release in releases)
    conflicts = sum(release.get("conflicts") or 0 for release in releases)
    return {
        "declared_expected": unavailable["declared_expected"],
        "expected": expected,
        "accepted": accepted,
        "conflicts": conflicts,
        "remaining": expected - accepted,
        "completion_percentage": (
            round((accepted / expected) * 100, 2) if expected else 0.0
        ),
    }
