"""Drift checks protecting stored immutable release revisions."""

from ..errors import CatalogError


def validate_existing_release(release, snapshot, *, product):
    if (
        release.product_id != product.pk
        or release.catalog_digest != snapshot.catalog_digest
        or release.description != snapshot.description
        or release.coverage_state != snapshot.coverage_state
        or release.source_kind != snapshot.source_kind
    ):
        raise CatalogError(
            "immutable_release_changed",
            "Release '{}', revision {} already exists with different content.".format(
                snapshot.release_key,
                snapshot.revision,
            ),
        )
    _validate_product_unit_records(release, snapshot)
    _validate_definition_links(release, snapshot)


def _validate_product_unit_records(release, snapshot):
    stored = set(
        release.product_units.values_list(
            "product_unit_code",
            "source_value",
            "provenance",
        )
    )
    expected = {
        (product_unit_code, source_value, snapshot.product_unit_provenance)
        for product_unit_code, source_value in zip(
            snapshot.product_unit_codes,
            snapshot.product_unit_source_values,
        )
    }
    if stored != expected:
        raise CatalogError(
            "release_product_unit_drift",
            "Stored product units differ from the immutable release snapshot.",
        )


def _validate_definition_links(release, snapshot):
    stored = set(
        release.definition_links.values_list(
            "qc_definition__product_ident",
            "qc_definition__digest",
            "is_primary",
        )
    )
    expected = {
        (
            definition.product_ident,
            definition.digest,
            definition.product_ident == snapshot.primary_definition_ident,
        )
        for definition in snapshot.definitions
    }
    if stored != expected:
        raise CatalogError(
            "release_definition_drift",
            "Stored QC definitions differ from the immutable release snapshot.",
        )
