"""Creation of complete immutable product-release records."""

from dataclasses import replace

from django.utils import timezone

from qc_tool.frontend.dashboard.models import ProductUnit
from qc_tool.frontend.dashboard.models import ProductRelease
from qc_tool.frontend.dashboard.models import ProductReleaseDefinition

from ..errors import CatalogError


def find_existing_release(snapshot):
    return ProductRelease.objects.filter(
        release_key=snapshot.release_key,
        revision=snapshot.revision,
    ).first()


def create_release(snapshot, *, product, definitions, result):
    previous = (
        ProductRelease.objects.filter(release_key=snapshot.release_key)
        .order_by("-revision")
        .first()
    )
    _validate_new_revision(snapshot, product=product, previous=previous)
    release = ProductRelease.objects.create(
        product=product,
        release_key=snapshot.release_key,
        revision=snapshot.revision,
        description=snapshot.description,
        catalog_digest=snapshot.catalog_digest,
        source_kind=snapshot.source_kind,
        coverage_state=snapshot.coverage_state,
        is_current=False,
        supersedes=previous,
        approved_at=(
            timezone.now()
            if snapshot.coverage_state
            == ProductRelease.CoverageState.AUTHORITATIVE
            else None
        ),
    )
    _create_definition_links(release, snapshot, definitions)
    _create_required_units(release, snapshot)
    result = replace(
        result,
        releases_created=result.releases_created + 1,
        product_units_created=result.product_units_created + len(snapshot.product_unit_codes),
    )
    return release, result


def _validate_new_revision(snapshot, *, product, previous):
    if previous is not None and previous.product_id != product.pk:
        raise CatalogError(
            "release_key_collision",
            "A release key cannot be shared by different products.",
        )
    if previous is not None and snapshot.revision <= previous.revision:
        raise CatalogError(
            "invalid_release_revision",
            "A changed release must use a higher revision number.",
        )


def _create_definition_links(release, snapshot, definitions):
    ProductReleaseDefinition.objects.bulk_create(
        [
            ProductReleaseDefinition(
                product_release=release,
                qc_definition=definition,
                is_primary=(ident == snapshot.primary_definition_ident),
            )
            for ident, definition in definitions.items()
        ]
    )


def _create_required_units(release, snapshot):
    ProductUnit.objects.bulk_create(
        [
            ProductUnit(
                product_release=release,
                product_unit_code=product_unit_code,
                source_value=source_value,
                provenance=snapshot.product_unit_provenance,
            )
            for product_unit_code, source_value in zip(
                snapshot.product_unit_codes,
                snapshot.product_unit_source_values,
            )
        ],
        batch_size=1_000,
    )
