#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import re


AOI_CODE_KEY = "aoi_code"

# Product definitions and external datasets use several names for the same
# identifier. These spellings are accepted only at the naming/input boundary;
# all internal and persisted metadata uses AOI_CODE_KEY.
_AOI_INPUT_ALIASES = (
    AOI_CODE_KEY,
    "delivery_unit_id",
    "fua_code",
    "fua",
    "du_id",
    "du",
    "code_city",
    "codecity",
)

_STANDARD_AOI_PATTERNS = (
    # Legacy Urban Atlas names include a final sub-unit/revision digit, while
    # current names and boundary data use the six-character FUA identifier.
    re.compile(
        r"^(?P<aoi_code>[a-z]{2}[0-9]{3}l)(?:[0-9xy])?$",
        re.IGNORECASE,
    ),
    # N2K delivery names include a letter suffix, while their shared delivery
    # unit identifier and the related RPZ products use DU plus three digits.
    re.compile(r"^(?P<aoi_code>du[0-9]{3})(?:[a-z])?$", re.IGNORECASE),
)


def _normalize_alias(alias):
    if not isinstance(alias, str):
        return None
    return re.sub(r"[^a-z0-9]", "", alias.casefold())


_NORMALIZED_AOI_INPUT_ALIASES = tuple(dict.fromkeys(
    _normalize_alias(alias) for alias in _AOI_INPUT_ALIASES
))

_AOI_NAMING_CHECKS = {
    "qc_tool.raster.naming": ("raster", "layer_names"),
    "qc_tool.vector.naming": ("vector", "layer_names"),
    "qc_tool.vector.naming_pdf": (None, "document_names"),
}

_AOI_VALIDATION_STEP_MEDIA = {
    "qc_tool.raster.naming": "raster",
    "qc_tool.vector.import2pg": "vector",
}

# Some immutable product definitions predate boundary-backed AOI validation.
# Keep the missing product-to-boundary metadata in one application-owned
# registry rather than duplicating spatial lookup rules in raster and vector
# checks or guessing a boundary from an AOI code that may occur in many files.
_AOI_VALIDATION_OVERRIDES = {
    "clms_hrlslf_wvl_s2018_r005m_gf": {
        "validator": "raster", "source_type": "raster", "mask": "eea38uk_100km"
    },
    "clms_hrlslf_wvl_s2018_r005m_gp": {
        "validator": "raster", "source_type": "raster", "mask": "eea38uk_100km"
    },
    "clms_hrlslf_wvl_s2018_r005m_mq": {
        "validator": "raster", "source_type": "raster", "mask": "eea38uk_100km"
    },
    "clms_hrlslf_wvl_s2018_r005m_re": {
        "validator": "raster", "source_type": "raster", "mask": "eea38uk_100km"
    },
    "clms_hrlslf_wvl_s2018_r005m_yt": {
        "validator": "raster", "source_type": "raster", "mask": "eea38uk_100km"
    },
    "clms_ua_bbh_s2021_r10m": {
        "validator": "raster", "source_type": "vector",
        "source": "boundary_ua2021_eea39_v3.gpkg", "code_field": "fua_code"
    },
    "clms_ua_bbh_s2024_r10m": {
        "validator": "raster", "source_type": "vector",
        "source": "boundary_ua2024_eea39_v1.gpkg", "code_field": "fua_code"
    },
    "ua2012_dhm": {
        "validator": "raster", "source_type": "vector",
        "source": "boundary_ua2012_dhm.gpkg", "code_field": "code_city"
    },
    "clms_ua_stl_s2021_vec": {
        "validator": "vector", "source_type": "vector",
        "source": "boundary_ua2021_eea39_v3.gpkg", "code_field": "fua_code"
    },
    "clms_ua_lcuc_c2018-2021_v010ha": {
        "validator": "vector", "source_type": "vector",
        "source": "boundary_ua2021_eea39_v3.gpkg", "code_field": "fua_code"
    },
    "clms_ua_lcuc_c2021-2024_v010ha": {
        "validator": "vector", "source_type": "vector",
        "source": "boundary_ua2024_eea39_v1.gpkg", "code_field": "fua_code"
    },
    "n2k_2012_change": {
        "validator": "vector", "source_type": "vector",
        "source": "boundary_n2k.gpkg", "code_field": "du_id"
    },
    "n2k_2018_change": {
        "validator": "vector", "source_type": "vector",
        "source": "boundary_n2k.gpkg", "code_field": "du_id"
    },
    "ua2018_stl": {
        "validator": "vector", "source_type": "vector",
        "source": "boundary_ua.gpkg", "code_field": "fua_code"
    },
    "ua_change_2012_2018": {
        "validator": "vector", "source_type": "vector",
        "source": "boundary_ua.gpkg", "code_field": "fua_code"
    },
}

# These products claim an AOI but the current boundary package does not map
# that delivery identifier to an authoritative geometry. Keep them explicit
# and fail closed rather than validating against a guessed or product-wide
# polygon. A future mapping can move from this set into the registry above.
_AOI_VALIDATION_UNSUPPORTED = {
    "clms_euhydro_acc_ie_nir",
    "clms_euhydro_art_ie_nir",
    "clms_euhydro_bas_ie_nir",
    "clms_euhydro_coast_ie_nir",
    "clms_euhydro_dem_ie_nir",
    "clms_euhydro_dir_ie_nir",
    "clms_euhydro_net_ie_nir",
    "clms_euhydro_wbo_ie_nir",
    "cz_2012",
    "cz_2018",
    "cz_change_2012_2018",
}


def is_aoi_input_alias(alias):
    """Return whether *alias* is an accepted input spelling for an AOI code."""
    return _normalize_alias(alias) in _NORMALIZED_AOI_INPUT_ALIASES


def aoi_input_aliases_equivalent(first, second):
    """Compare external AOI field names case- and separator-insensitively."""
    first_normalized = _normalize_alias(first)
    return (
        first_normalized is not None
        and first_normalized == _normalize_alias(second)
    )


def normalize_aoi_code(value):
    """Return the stable lowercase AOI identifier used in results and the DB."""
    if not isinstance(value, str):
        return None

    normalized = value.strip().casefold()
    if not normalized:
        return None

    for pattern in _STANDARD_AOI_PATTERNS:
        match = pattern.fullmatch(normalized)
        if match is not None:
            return match.group(AOI_CODE_KEY).casefold()
    return normalized


def aoi_codes_equivalent(first, second):
    """Compare AOI values without rewriting the product-specific raw value."""
    first_normalized = normalize_aoi_code(first)
    second_normalized = normalize_aoi_code(second)
    if first_normalized is None or second_normalized is None:
        return False
    if first_normalized == second_normalized:
        return True

    # Some combined raster/vector products use zero-padded and unpadded forms
    # for the same numeric AOI. Keep the first form but compare by value.
    if first_normalized.isdecimal() and second_normalized.isdecimal():
        return int(first_normalized) == int(second_normalized)
    return False


def has_aoi_code_capture(regex):
    """Return whether a regular expression contains a known AOI code group."""
    return any(is_aoi_input_alias(group_name) for group_name in re.compile(regex).groupindex)


def extract_aoi_code_from_groups(groups):
    """Resolve product-specific named groups to one unambiguous AOI value.

    Alias names are matched case- and separator-insensitively. If a regex ever
    publishes more than one AOI alias, all populated values must be equivalent.
    The raw value from the preferred alias is returned so existing downstream
    product checks continue to receive the representation defined by that
    product. Call :func:`normalize_aoi_code` for result or database metadata.
    """
    if not isinstance(groups, dict):
        return None

    candidates = []
    for alias_index, normalized_alias in enumerate(_NORMALIZED_AOI_INPUT_ALIASES):
        for group_name, value in groups.items():
            if _normalize_alias(group_name) != normalized_alias:
                continue
            if not isinstance(value, str) or not value.strip():
                continue
            candidates.append((alias_index, value.strip()))

    if not candidates:
        return None

    candidates.sort(key=lambda candidate: candidate[0])
    selected = candidates[0][1]
    if any(not aoi_codes_equivalent(selected, candidate[1]) for candidate in candidates[1:]):
        raise ValueError("AOI capture groups contain conflicting values")
    return selected


def extract_aoi_code(layer_defs, layer_regexes, expected_aoi_codes, status,
                     preserve_aoicode_case=False, compare_aoi_codes=True):
    """Extract one AOI from all matched delivery layers.

    AOI-less products do not call this function. For AOI-bearing products,
    every relevant layer must publish one equivalent value and, when present,
    that value must belong to the product's immutable allowlist.
    """
    layer_aoi_codes = []
    invalid_aoi_code = False
    for layer_alias, layer_def in layer_defs.items():
        layer_name = layer_def["src_layer_name"]
        groups = layer_def.get("groups")
        if groups is None:
            layer_regex = layer_regexes[layer_alias]
            flags = re.IGNORECASE if preserve_aoicode_case else 0
            match = re.match(layer_regex, layer_name if preserve_aoicode_case else layer_name.lower(), flags)
            if match is None:
                status.aborted("Layer {:s} has illegal name: {:s}.".format(layer_alias, layer_name))
                invalid_aoi_code = True
                continue
            groups = match.groupdict()
        try:
            groups = canonicalize_aoi_capture_groups(groups)
        except ValueError:
            status.aborted("Layer {:s} contains conflicting AOI code captures.".format(layer_name))
            invalid_aoi_code = True
            continue
        aoi_code = groups.get(AOI_CODE_KEY)
        if aoi_code is None:
            status.aborted("Layer {:s} does not contain AOI code.".format(layer_name))
            invalid_aoi_code = True
            continue
        if not preserve_aoicode_case:
            aoi_code = aoi_code.casefold()
        layer_aoi_codes.append(aoi_code)

        if compare_aoi_codes and not any(
            aoi_codes_equivalent(aoi_code, expected_aoi_code)
            for expected_aoi_code in expected_aoi_codes
        ):
            status.aborted("Layer {:s} has illegal AOI code {:s}.".format(layer_name, aoi_code))
            invalid_aoi_code = True

    if not layer_aoi_codes:
        status.aborted("AOI code could not be detected from any layer name.")
        return None

    first_aoi_code = layer_aoi_codes[0]
    if any(not aoi_codes_equivalent(first_aoi_code, candidate)
           for candidate in layer_aoi_codes[1:]):
        status.aborted(
            "Layers do not have the same AOI code. Detected AOI codes: {:s}"
            .format(",".join(layer_aoi_codes))
        )
        return None

    if invalid_aoi_code:
        return None
    return first_aoi_code


def invalidate_aoi_code(status, message):
    """Abort AOI validation and prevent a later naming stage restoring it."""
    status.aborted(message)
    clear_aoi_code(status)
    status.add_params({"_aoi_code_invalid": True})


def clear_aoi_code(status):
    """Remove unvalidated AOI metadata without changing the check status."""
    status.add_params({
        AOI_CODE_KEY: None,
        "_aoi_validated_media": (),
        "_aoi_not_applicable_media": (),
    })
    status.set_status_property(AOI_CODE_KEY, None)


def publish_aoi_code(params, status, aoi_code):
    """Publish one unambiguous AOI code for downstream checks and reporting."""
    previous_aoi_code = params.get(AOI_CODE_KEY)

    if params.get("_aoi_code_conflict", False) or params.get("_aoi_code_invalid", False):
        clear_aoi_code(status)
        status.add_params({"_aoi_code_conflict": True})
        return None

    canonical_aoi_code = normalize_aoi_code(aoi_code)
    if canonical_aoi_code is None:
        clear_aoi_code(status)
        if isinstance(previous_aoi_code, str) and previous_aoi_code:
            status.add_params({"_aoi_code_conflict": True})
        return None

    if isinstance(previous_aoi_code, str) and previous_aoi_code:
        if not aoi_codes_equivalent(previous_aoi_code, aoi_code):
            invalidate_aoi_code(
                status,
                "AOI code '{:s}' does not match the previously detected AOI code '{:s}'."
                .format(aoi_code, previous_aoi_code),
            )
            status.add_params({"_aoi_code_conflict": True})
            return None
        aoi_code = previous_aoi_code

    status.add_params({AOI_CODE_KEY: aoi_code.strip()})
    # Spatial products need the raw code for downstream checks, but it must not
    # become result/database metadata until every required medium has either
    # confirmed it or been explicitly identified as empty/not applicable.
    _publish_completed_aoi(
        params,
        status,
        aoi_code,
        set(params.get("_aoi_validated_media", ())),
        set(params.get("_aoi_not_applicable_media", ())),
    )
    return aoi_code.strip()


def resolve_single_aoi_code(values):
    """Normalize a collection that must identify at most one AOI."""
    candidates = [value for value in values if normalize_aoi_code(value) is not None]
    if not candidates:
        return None
    first = candidates[0]
    if any(not aoi_codes_equivalent(first, candidate) for candidate in candidates[1:]):
        raise ValueError(
            "multiple AOI codes were detected: {:s}"
            .format(", ".join(sorted(set(normalize_aoi_code(value) for value in candidates))))
        )
    return normalize_aoi_code(first)


def _required_aoi_media(params):
    validation_plan = params.get("aoi_validation_plan", {})
    if not isinstance(validation_plan, dict):
        return set()
    return set(validation_plan.get("media", ()))


def validate_spatial_aoi_codes(params, status, detected_codes, medium=None):
    """Confirm that spatial analysis found exactly the one AOI named by the job."""
    claimed_code = params.get(AOI_CODE_KEY)
    if normalize_aoi_code(claimed_code) is None:
        return None

    try:
        detected_code = resolve_single_aoi_code(detected_codes)
    except ValueError as exc:
        invalidate_aoi_code(status, "Spatial AOI validation failed: {:s}.".format(str(exc)))
        return None
    if detected_code is None:
        invalidate_aoi_code(status, "Dataset does not overlap its claimed AOI boundary.")
        return None
    if not aoi_codes_equivalent(claimed_code, detected_code):
        invalidate_aoi_code(
            status,
            "AOI code '{:s}' does not match the spatially detected AOI code '{:s}'."
            .format(normalize_aoi_code(claimed_code), detected_code),
        )
        return None

    required_media = _required_aoi_media(params)
    validated_media = set(params.get("_aoi_validated_media", ()))
    not_applicable_media = set(params.get("_aoi_not_applicable_media", ()))
    if required_media:
        validated_media.intersection_update(required_media)
        not_applicable_media.intersection_update(required_media)
    if medium is not None and (not required_media or medium in required_media):
        validated_media.add(medium)
    not_applicable_media.discard(medium)
    status.add_params({
        AOI_CODE_KEY: claimed_code.strip(),
        "_aoi_validated_media": tuple(sorted(validated_media)),
        "_aoi_not_applicable_media": tuple(sorted(not_applicable_media)),
    })
    _publish_completed_aoi(
        params, status, claimed_code, validated_media, not_applicable_media
    )
    return normalize_aoi_code(claimed_code)


def _publish_completed_aoi(
    params, status, claimed_code, validated_media, not_applicable_media
):
    """Publish after every required medium is validated or not applicable."""
    required_media = _required_aoi_media(params)
    required_validated_media = validated_media.intersection(required_media)
    validation_complete = (
        not required_media
        or (
            bool(required_validated_media)
            and required_media.issubset(
                validated_media.union(not_applicable_media)
            )
        )
    )
    if validation_complete:
        status.set_status_property(
            AOI_CODE_KEY, normalize_aoi_code(claimed_code)
        )
    else:
        status.set_status_property(AOI_CODE_KEY, None)


def mark_aoi_medium_not_applicable(params, status, medium):
    """Record that an empty medium has no geometry to validate for this AOI."""
    claimed_code = params.get(AOI_CODE_KEY)
    if normalize_aoi_code(claimed_code) is None:
        return None

    required_media = _required_aoi_media(params)
    validated_media = set(params.get("_aoi_validated_media", ()))
    not_applicable_media = set(params.get("_aoi_not_applicable_media", ()))
    if required_media:
        validated_media.intersection_update(required_media)
        not_applicable_media.intersection_update(required_media)
    validated_media.discard(medium)
    if not required_media or medium in required_media:
        not_applicable_media.add(medium)
    status.add_params({
        AOI_CODE_KEY: claimed_code.strip(),
        "_aoi_validated_media": tuple(sorted(validated_media)),
        "_aoi_not_applicable_media": tuple(sorted(not_applicable_media)),
    })
    _publish_completed_aoi(
        params, status, claimed_code, validated_media, not_applicable_media
    )
    return normalize_aoi_code(claimed_code)


def product_aoi_media(product_definition):
    """Return spatial media whose naming rules claim an AOI."""
    media = set()
    for step in product_definition.get("steps", []):
        check_ident = step.get("check_ident")
        naming_info = _AOI_NAMING_CHECKS.get(check_ident)
        if naming_info is None:
            continue
        medium, regex_key = naming_info
        regexes = step.get("parameters", {}).get(regex_key, {}).values()
        if any(has_aoi_code_capture(regex) for regex in regexes) and medium is not None:
            media.add(medium)
    return media


def product_uses_aoi(product_definition):
    """Return whether any naming rule publishes an AOI, including documents."""
    for step in product_definition.get("steps", []):
        naming_info = _AOI_NAMING_CHECKS.get(step.get("check_ident"))
        if naming_info is None:
            continue
        regex_key = naming_info[1]
        regexes = step.get("parameters", {}).get(regex_key, {}).values()
        if any(has_aoi_code_capture(regex) for regex in regexes):
            return True
    return False


def _configured_raster_contract(product_definition):
    naming_layer_names = next((
        step.get("parameters", {}).get("layer_names", {})
        for step in product_definition.get("steps", [])
        if step.get("check_ident") == "qc_tool.raster.naming"
    ), None)
    if not naming_layer_names:
        return None
    naming_layers = set(naming_layer_names)
    checks = []
    for step in product_definition.get("steps", []):
        if step.get("check_ident") != "qc_tool.raster.gap":
            continue
        parameters = step.get("parameters", {})
        mask = parameters.get("mask", "default")
        source_type = "vector" if mask.lower().endswith((".gpkg", ".shp")) else "raster"
        check = {
            "source_type": source_type,
            "layers": tuple(parameters.get("layers", ())),
        }
        if source_type == "vector":
            check.update({"source": mask, "code_field": parameters.get("du_column_name")})
        else:
            check["mask"] = mask
        if check not in checks:
            checks.append(check)
    if not checks:
        return None

    covered_layers = set()
    for check in checks:
        covered_layers.update(check["layers"] or naming_layers)
    if covered_layers != naming_layers:
        return None
    return {"validator": "raster", "checks": tuple(checks)}


def _configured_vector_contract(product_definition):
    naming_step = next((
        step for step in product_definition.get("steps", [])
        if step.get("check_ident") == "qc_tool.vector.naming"
        and step.get("parameters", {}).get("boundary_source")
    ), None)
    if naming_step is None:
        return None

    gap_steps = [
        step for step in product_definition.get("steps", [])
        if step.get("check_ident") == "qc_tool.vector.gap"
    ]
    code_field = None
    for step in gap_steps:
        parameters = step.get("parameters", {})
        if parameters.get("du_column_name") is not None:
            code_field = parameters["du_column_name"]
    return {
        "validator": "vector",
        "source_type": "vector",
        "source": naming_step["parameters"]["boundary_source"],
        "code_field": code_field,
        "layers": tuple(
            naming_step.get("parameters", {}).get("layer_names", {})
        ),
    }


def build_aoi_validation_plan(product_definition):
    """Build an immutable-definition-derived AOI validation plan for one job."""
    media = product_aoi_media(product_definition)
    product_ident = product_definition.get("product_ident", "").casefold()
    if not media:
        return {
            "uses_aoi": product_uses_aoi(product_definition),
            "media": (),
            "contracts": {},
        }

    contracts = {medium: None for medium in sorted(media)}
    if product_ident not in _AOI_VALIDATION_UNSUPPORTED:
        if "raster" in media:
            contracts["raster"] = _configured_raster_contract(
                product_definition
            )
        if "vector" in media:
            contracts["vector"] = _configured_vector_contract(
                product_definition
            )

        override = _AOI_VALIDATION_OVERRIDES.get(product_ident)
        if override is not None:
            contract = dict(override)
            medium = contract["validator"]
            if medium == "raster":
                contract = {"validator": "raster", "checks": (contract,)}
            else:
                naming_step = next(
                    step for step in product_definition.get("steps", [])
                    if step.get("check_ident") == "qc_tool.vector.naming"
                )
                contract["layers"] = tuple(
                    naming_step.get("parameters", {}).get("layer_names", {})
                )
            contracts[medium] = contract

        # Mixed SWF deliveries use the same configured AOI raster mask for
        # both media. The vector adapter checks its imported geometry against
        # those actual mask pixels after import.
        if (
            "vector" in media
            and contracts.get("vector") is None
            and contracts.get("raster")
        ):
            contracts["vector"] = {
                "validator": "vector",
                "source_type": "raster",
                "checks": contracts["raster"]["checks"],
                "layers": tuple(
                    next(
                        step for step in product_definition.get("steps", [])
                        if step.get("check_ident") == "qc_tool.vector.naming"
                    ).get("parameters", {}).get("layer_names", {})
                ),
            }

    return {
        "uses_aoi": True,
        "media": tuple(sorted(media)),
        "contracts": contracts,
        "product_ident": product_ident,
    }


def validate_after_step(check_ident, params, status):
    """Run the product's non-skippable spatial AOI adapter at a safe step."""
    plan = params.get("aoi_validation_plan")
    if not isinstance(plan, dict) or not plan.get("media"):
        return

    medium = _AOI_VALIDATION_STEP_MEDIA.get(check_ident)
    if medium not in plan["media"]:
        return

    if status.status != "ok":
        clear_aoi_code(status)
        return

    contract = plan.get("contracts", {}).get(medium)
    if contract is None:
        invalidate_aoi_code(
            status,
            "Product {:s} claims an AOI but has no authoritative {:s} "
            "boundary mapping."
            .format(plan.get("product_ident") or "<unknown>", medium),
        )
        return

    if medium == "raster":
        from qc_tool.raster.aoi import validate_aoi
    else:
        from qc_tool.vector.aoi import validate_aoi
    validate_aoi(params, status, contract)


def clear_aoi_after_failed_step(check_ident, params, status):
    """Clear a claimed AOI when its required spatial hook did not complete."""
    plan = params.get("aoi_validation_plan")
    if not isinstance(plan, dict):
        return
    if _AOI_VALIDATION_STEP_MEDIA.get(check_ident) in plan.get("media", ()):
        clear_aoi_code(status)


def canonicalize_aoi_capture_groups(groups):
    """Replace every recognized AOI input group with only ``aoi_code``.

    Other named captures, such as ``epsg_code`` and ``fua_name``, are retained.
    The AOI value remains in its product-specific form for downstream checks;
    result and database metadata is normalized by :func:`normalize_aoi_code`.
    """
    if not isinstance(groups, dict):
        return {}

    aoi_code = extract_aoi_code_from_groups(groups)
    canonical_groups = {
        group_name: value
        for group_name, value in groups.items()
        if not is_aoi_input_alias(group_name)
    }
    if aoi_code is not None:
        canonical_groups[AOI_CODE_KEY] = aoi_code
    return canonical_groups
