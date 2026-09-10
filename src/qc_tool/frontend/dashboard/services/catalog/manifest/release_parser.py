"""Release-level manifest schema parsing."""

from qc_tool.product_security import normalize_product_ident

from ..contracts import ReleaseSnapshot
from .constants import MAX_DEFINITIONS_PER_RELEASE
from .constants import VALID_COVERAGE_STATES
from .coverage import extract_coverage_aois
from .digests import calculate_release_digest
from .validation import invalid_manifest
from .validation import required_text


def parse_release_document(
    document,
    *,
    product_ident,
    product_name,
    product_description,
    definition_loader,
    source_kind="manifest",
):
    if not isinstance(document, dict):
        raise invalid_manifest("every release must be an object")
    release_key = required_text(document, "release_key", maximum=100)
    revision = document.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise invalid_manifest("release revision must be a positive integer")
    description = required_text(document, "description", maximum=500)
    is_current = document.get("is_current", True)
    if not isinstance(is_current, bool):
        raise invalid_manifest("is_current must be a boolean")

    definition_idents, primary_ident = parse_definition_idents(document)
    definitions = tuple(
        definition_loader(ident) for ident in definition_idents
    )
    coverage = document.get("coverage", {"state": "unknown"})
    if not isinstance(coverage, dict):
        raise invalid_manifest("coverage must be an object")
    coverage_state = coverage.get("state", "unknown")
    if coverage_state not in VALID_COVERAGE_STATES:
        raise invalid_manifest("coverage state is invalid")
    aoi_codes, source_values, provenance = extract_coverage_aois(
        coverage,
        definitions,
        state=coverage_state,
    )
    catalog_digest = calculate_release_digest(
        product_ident=product_ident,
        release_key=release_key,
        revision=revision,
        description=description,
        coverage_state=coverage_state,
        definitions=definitions,
        primary_definition_ident=primary_ident,
        aoi_codes=aoi_codes,
        source_kind=source_kind,
    )
    return ReleaseSnapshot(
        product_ident=product_ident,
        product_name=product_name,
        product_description=product_description,
        release_key=release_key,
        revision=revision,
        description=description,
        coverage_state=coverage_state,
        is_current=is_current,
        definitions=definitions,
        primary_definition_ident=primary_ident,
        aoi_codes=tuple(aoi_codes),
        aoi_source_values=tuple(source_values),
        aoi_provenance=provenance,
        catalog_digest=catalog_digest,
        source_kind=source_kind,
    )


def parse_definition_idents(document):
    definition_idents = document.get("definition_idents")
    if (
        not isinstance(definition_idents, list)
        or not definition_idents
        or len(definition_idents) > MAX_DEFINITIONS_PER_RELEASE
    ):
        raise invalid_manifest(
            "definition_idents must be a non-empty bounded list"
        )
    canonical_idents = tuple(
        normalize_product_ident(ident) for ident in definition_idents
    )
    if any(ident is None for ident in canonical_idents):
        raise invalid_manifest(
            "definition identifiers must be routable, non-reserved identifiers"
        )
    if len(set(canonical_idents)) != len(canonical_idents):
        raise invalid_manifest("definition identifiers must be unique")
    primary_ident = document.get("primary_definition", canonical_idents[0])
    primary_ident = normalize_product_ident(primary_ident)
    if primary_ident is None:
        raise invalid_manifest(
            "primary_definition must be a routable, non-reserved identifier"
        )
    if primary_ident not in canonical_idents:
        raise invalid_manifest(
            "primary_definition must belong to definition_idents"
        )
    return canonical_idents, primary_ident
