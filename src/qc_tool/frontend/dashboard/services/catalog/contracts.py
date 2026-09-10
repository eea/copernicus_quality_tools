"""Immutable catalog import and reporting contracts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DefinitionSnapshot:
    product_ident: str
    description: str
    digest: str
    document: dict
    source_path: str


@dataclass(frozen=True)
class ReleaseSnapshot:
    product_ident: str
    product_name: str
    product_description: str
    release_key: str
    revision: int
    description: str
    coverage_state: str
    is_current: bool
    definitions: tuple
    primary_definition_ident: str
    aoi_codes: tuple
    aoi_source_values: tuple
    aoi_provenance: str
    catalog_digest: str
    source_kind: str = "manifest"


@dataclass(frozen=True)
class CatalogSnapshot:
    releases: tuple


@dataclass(frozen=True)
class CatalogSyncResult:
    releases_scanned: int = 0
    definitions_created: int = 0
    products_created: int = 0
    products_updated: int = 0
    releases_created: int = 0
    aois_created: int = 0
    current_pointers_changed: int = 0

    @property
    def changed(self):
        return any(
            (
                self.definitions_created,
                self.products_created,
                self.products_updated,
                self.releases_created,
                self.aois_created,
                self.current_pointers_changed,
            )
        )


@dataclass(frozen=True)
class ProductCoverage:
    release_id: int
    coverage_state: str
    expected: int | None
    submitted: int | None
    conflicts: int | None
    remaining: int | None
    completion_percentage: float | None
