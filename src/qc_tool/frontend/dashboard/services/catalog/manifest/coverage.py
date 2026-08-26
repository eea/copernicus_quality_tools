"""Expected-AOI extraction and normalization for release coverage."""

from qc_tool.aoi import normalize_aoi_code
from qc_tool.product_security import normalize_product_ident

from .constants import MAX_AOIS_PER_RELEASE
from .constants import NAMING_CHECK_SUFFIXES
from .validation import invalid_manifest


def extract_coverage_aois(coverage, definitions, *, state):
    explicit = coverage.get("aoi_codes")
    source_ident = coverage.get("source_definition")
    if explicit is not None and source_ident is not None:
        raise invalid_manifest("coverage must use one AOI source")
    if explicit is not None:
        raw_codes = explicit
        provenance = "manifest"
    elif source_ident is not None:
        source_ident = normalize_product_ident(source_ident)
        if source_ident is None:
            raise invalid_manifest(
                "source_definition must be a routable, non-reserved identifier"
            )
        matches = [
            definition
            for definition in definitions
            if definition.product_ident == source_ident
        ]
        if len(matches) != 1:
            raise invalid_manifest("source_definition must belong to the release")
        raw_codes = extract_definition_aoi_codes(matches[0].document)
        provenance = "definition"
    else:
        raw_codes = []
        provenance = "manifest"

    if not isinstance(raw_codes, list):
        raise invalid_manifest("aoi_codes must be a list")
    if len(raw_codes) > MAX_AOIS_PER_RELEASE:
        raise invalid_manifest("aoi_codes exceeds the per-release limit")
    if raw_codes and raw_codes[0] == "*":
        raise invalid_manifest("wildcard AOI lists cannot define coverage")

    canonical_to_source = {}
    for raw_code in raw_codes:
        canonical = normalize_aoi_code(raw_code)
        if canonical is None:
            raise invalid_manifest("aoi_codes contains an invalid value")
        canonical_to_source.setdefault(canonical, str(raw_code))
    if state == "authoritative" and not canonical_to_source:
        raise invalid_manifest("authoritative coverage requires expected AOIs")
    if state == "unknown" and canonical_to_source:
        raise invalid_manifest("unknown coverage cannot contain expected AOIs")
    ordered = sorted(canonical_to_source)
    return (
        ordered,
        [canonical_to_source[code] for code in ordered],
        provenance,
    )


def extract_definition_aoi_codes(document):
    sets = []
    for step in document.get("steps", []):
        if not isinstance(step, dict):
            continue
        check_ident = step.get("check_ident")
        if not isinstance(check_ident, str) or not check_ident.endswith(
            NAMING_CHECK_SUFFIXES
        ):
            continue
        parameters = step.get("parameters", {})
        if not isinstance(parameters, dict) or "aoi_codes" not in parameters:
            continue
        raw_codes = parameters["aoi_codes"]
        if not isinstance(raw_codes, list) or (raw_codes and raw_codes[0] == "*"):
            raise invalid_manifest("definition does not contain a finite AOI list")
        canonical = {normalize_aoi_code(value) for value in raw_codes}
        if None in canonical:
            raise invalid_manifest("definition contains an invalid AOI")
        sets.append((canonical, raw_codes))
    if not sets:
        raise invalid_manifest("definition does not declare expected AOIs")
    reference = sets[0][0]
    if any(values != reference for values, _raw in sets[1:]):
        raise invalid_manifest(
            "definition naming checks disagree on expected AOIs"
        )
    return sets[0][1]
