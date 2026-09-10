"""Explicit directory imports using the same revision graph as curated catalogs."""

from dataclasses import dataclass
from dataclasses import replace

from django.db import transaction
from django.db.models import Q

from qc_tool.frontend.dashboard.models import Product
from qc_tool.frontend.dashboard.models import ProductRelease

from .contracts import CatalogSyncResult
from .definition_directory import declared_coverage
from .definition_directory import read_definition_directories
from .manifest.release_parser import parse_release_document
from .revisions import store_definition
from .sync.locks import lock_catalog_sync
from .sync.service import synchronize_release


@dataclass(frozen=True)
class DefinitionImportResult:
    catalog: CatalogSyncResult
    definitions_scanned: int
    managed_definitions: int
    unknown_scopes: int

    @property
    def changed(self):
        return self.catalog.changed


def synchronize_definition_directories(directories, *, dry_run=False):
    """Import snapshots and maintain only scopes owned by directory imports."""

    definitions = read_definition_directories(directories)
    # Scope validation, including disagreements between naming checks, must also
    # finish before opening the write transaction.
    coverages = tuple(declared_coverage(definition) for definition in definitions)
    result = CatalogSyncResult()
    managed = 0
    with transaction.atomic():
        lock_catalog_sync()
        for definition, coverage in zip(definitions, coverages):
            _stored, created = store_definition(definition)
            result = replace(
                result,
                definitions_created=result.definitions_created + int(created),
            )
            release_key = "definition:{}".format(definition.product_ident)
            latest = (
                ProductRelease.objects.filter(release_key=release_key)
                .order_by("-revision")
                .first()
            )
            if _managed_scope(definition.product_ident, release_key, latest):
                managed += 1
                continue
            revision = latest.revision if latest else 1
            snapshot = definition_release_snapshot(definition, coverage, release_key, revision)
            if latest and latest.catalog_digest != snapshot.catalog_digest:
                snapshot = definition_release_snapshot(
                    definition, coverage, release_key, revision + 1
                )
            result = synchronize_release(snapshot, result)
            result = replace(result, releases_scanned=result.releases_scanned + 1)
        if dry_run:
            transaction.set_rollback(True)
    return DefinitionImportResult(
        catalog=result,
        definitions_scanned=len(definitions),
        managed_definitions=managed,
        unknown_scopes=sum(coverage["state"] == "unknown" for coverage in coverages),
    )


def _managed_scope(ident, release_key, latest):
    if Product.objects.filter(ident=ident, is_active=False).exists():
        return True
    if latest is not None and (
        latest.source_kind != ProductRelease.SourceKind.DEFINITION
        or not latest.is_current
        or latest.coverage_state not in ("draft", "unknown")
    ):
        return True
    # Explicit product grouping, additional streams and retired catalogs all
    # retain operator ownership. Never resurrect them from directory contents.
    if ProductRelease.objects.filter(
        Q(product__ident=ident)
        | Q(definition_links__qc_definition__product_ident=ident)
    ).exclude(release_key=release_key).exists():
        return True
    return latest is None and Product.objects.filter(ident=ident).exists()


def definition_release_snapshot(
    definition, coverage, release_key, revision, *, source_kind="definition"
):
    return parse_release_document(
        {
            "release_key": release_key,
            "revision": revision,
            "description": definition.description,
            "definition_idents": [definition.product_ident],
            "coverage": coverage,
        },
        product_ident=definition.product_ident,
        product_name=definition.description[:200],
        product_description=definition.description,
        definition_loader=lambda _ident: definition,
        source_kind=source_kind,
    )
