"""Bounded, access-scoped history of immutable product specification files."""

from django.core.paginator import Paginator
from django.db.models import Q

from qc_tool.frontend.dashboard.models import ProductReleaseDefinition, QcDefinition
from qc_tool.frontend.dashboard.services.catalog.version_identity import release_version_identity


def specification_history(product_ident, account_access, *, page_number, is_active=True):
    """Include explicitly linked recipes without inferring families from names."""

    links = ProductReleaseDefinition.objects.filter(
        product_release__product__ident=product_ident,
    )
    versions = QcDefinition.objects.filter(
        Q(product_ident=product_ident) | Q(pk__in=links.values("qc_definition_id")),
    )
    if not account_access.can_access_product_snapshot(product_ident):
        versions = versions.filter(product_ident__in=account_access.product_idents)
    page = Paginator(versions.only(
        "product_ident", "digest", "imported_at",
    ).order_by("-imported_at", "-pk"), 20).get_page(page_number)
    snapshots = tuple(page)
    linked_versions = {}
    for link in links.filter(qc_definition_id__in=[item.pk for item in snapshots]).select_related(
        "product_release",
    ).order_by("product_release__release_key", "-product_release__revision"):
        linked_versions.setdefault(link.qc_definition_id, []).append(
            release_version_identity(link.product_release),
        )
    rows = tuple({
        "ident": version.product_ident,
        "digest": version.digest,
        "imported_at": version.imported_at,
        "series": tuple(linked_versions.get(version.pk, ())),
        "is_current": is_active and any(
            series["is_current"] for series in linked_versions.get(version.pk, ())
        ),
        "is_selected": any(
            series["is_current"] for series in linked_versions.get(version.pk, ())
        ),
    } for version in snapshots)
    return page, rows
