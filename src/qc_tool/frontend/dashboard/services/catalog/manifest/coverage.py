"""Business-unit declarations with explicit legacy geographic input support."""

from qc_tool.product_units import legacy_aoi_to_product_unit_code, normalize_product_unit_code
from qc_tool.product_security import normalize_product_ident

from .constants import MAX_PRODUCT_UNITS_PER_RELEASE, NAMING_CHECK_SUFFIXES
from .validation import invalid_manifest


def normalize_unit_list(raw_codes, *, legacy=False, allow_wildcard=False):
    if not isinstance(raw_codes, list) or len(raw_codes) > MAX_PRODUCT_UNITS_PER_RELEASE:
        raise invalid_manifest("product_units must be a bounded list of identifiers")
    normalize = legacy_aoi_to_product_unit_code if legacy else normalize_product_unit_code
    codes = {}
    for value in raw_codes:
        if value == "*" and allow_wildcard:
            codes[value] = value
            continue
        canonical = normalize(value)
        if canonical is None or any(char in canonical for char in "*?/\\") or canonical in (".", ".."):
            raise invalid_manifest("product_units contains an invalid or non-explicit identifier")
        codes.setdefault(canonical, value)
    return codes


def _declared_list(document):
    """Select one spelling without silently ignoring contradictory input."""

    keys = [key for key in ("product_units", "product_unit_codes", "aoi_codes") if key in document]
    if not keys:
        return None
    if len(keys) != 1:
        raise invalid_manifest("declare product units using only one field")
    key = keys[0]
    return document[key], key == "aoi_codes"


def naming_unit_scopes(document):
    """Return finite executable naming constraints and declaration flags."""

    scopes = []
    declared = False
    unbounded = False
    for step in document.get("steps", []):
        if not isinstance(step, dict) or not isinstance(step.get("check_ident"), str):
            continue
        if not step["check_ident"].endswith(NAMING_CHECK_SUFFIXES):
            continue
        parameters = step.get("parameters", {})
        # Built-in geographic naming checks execute this legacy parameter.
        # Top-level product_units is a separate business declaration; do not
        # pretend an unimplemented naming parameter constrains execution.
        selection = (
            (parameters["aoi_codes"], True)
            if isinstance(parameters, dict) and "aoi_codes" in parameters else None
        )
        if selection is None:
            continue
        declared = True
        values, legacy = selection
        codes = normalize_unit_list(values, legacy=legacy, allow_wildcard=True)
        if not codes or "*" in codes:
            unbounded = True
        else:
            scopes.append(codes)
    return scopes, declared, unbounded


def extract_definition_product_unit_codes(document):
    """Prefer explicit business units; geographic naming lists are legacy inputs."""

    return list(extract_definition_product_units(document))


def extract_definition_product_units(document):
    """Return canonical identities with their exact declared source values."""

    explicit = _declared_list(document)
    scopes, _declared, unbounded = naming_unit_scopes(document)
    if explicit is not None:
        values, legacy = explicit
        codes = normalize_unit_list(values, legacy=legacy)
        if not codes:
            raise invalid_manifest("product_units must contain at least one required unit")
        if scopes and not set(codes).issubset(set.intersection(*(set(scope) for scope in scopes))):
            raise invalid_manifest("declared product units are outside the specification's naming rules")
        return codes
    if not scopes or unbounded:
        raise invalid_manifest("definition does not declare a finite product-unit list")
    if any(set(scope) != set(scopes[0]) for scope in scopes[1:]):
        raise invalid_manifest("definition naming checks disagree on expected product units")
    # Values have already passed the legacy adapter, if one was needed.
    return scopes[0]


def extract_coverage_product_units(coverage, definitions, *, state):
    explicit = _declared_list(coverage)
    source_ident = coverage.get("source_definition")
    if explicit is not None and source_ident is not None:
        raise invalid_manifest("coverage must use one product unit source")
    if explicit is not None:
        values, legacy = explicit
        canonical_to_source = normalize_unit_list(values, legacy=legacy)
        provenance = "manifest"
    elif source_ident is not None:
        source_ident = normalize_product_ident(source_ident)
        matches = [definition for definition in definitions if definition.product_ident == source_ident]
        if source_ident is None or len(matches) != 1:
            raise invalid_manifest("source_definition must belong to the release")
        canonical_to_source = extract_definition_product_units(matches[0].document)
        provenance = "definition"
    else:
        canonical_to_source = {}
        provenance = "manifest"
    if state == "authoritative" and not canonical_to_source:
        raise invalid_manifest("authoritative coverage requires expected product units")
    if state == "unknown" and canonical_to_source:
        raise invalid_manifest("unknown coverage cannot contain expected product units")
    ordered = sorted(canonical_to_source)
    return ordered, [canonical_to_source[code] for code in ordered], provenance
