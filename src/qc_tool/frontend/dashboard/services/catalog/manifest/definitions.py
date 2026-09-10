"""Validated snapshots of executable QC definitions."""

import hashlib
import json
import math

from qc_tool.product_security import validate_executable_product_configuration
from qc_tool.product_security import normalize_product_ident

from ..contracts import DefinitionSnapshot
from ..errors import CatalogError


MAX_DEFINITION_BYTES = 1024 * 1024


def build_definition_snapshot(product_ident, *, locate_definition):
    canonical_ident = normalize_product_ident(product_ident)
    if canonical_ident is None:
        raise CatalogError(
            "definition_unavailable",
            "The product definition identifier is invalid.",
        )
    try:
        path = locate_definition(canonical_ident)
        with path.open("rb") as source:
            payload = source.read(MAX_DEFINITION_BYTES + 1)
    except Exception as exc:
        raise CatalogError(
            "definition_unavailable",
            "The product definition could not be read.",
        ) from exc
    return parse_definition_snapshot(canonical_ident, payload, source_path=str(path))


def parse_definition_snapshot(product_ident, payload, *, source_path):
    """Validate uploaded or file-backed bytes without depending on a path."""

    canonical_ident = normalize_product_ident(product_ident)
    if canonical_ident is None:
        raise CatalogError("definition_unavailable", "The product identifier is invalid.")
    try:
        if len(payload) > MAX_DEFINITION_BYTES:
            raise ValueError("definition exceeds the size limit")
        document = json.loads(
            payload.decode("utf-8"),
            parse_constant=_invalid_json_constant,
            parse_float=_finite_json_float,
            object_pairs_hook=_unique_json_object,
        )
        _validate_json_strings(document)
        validate_executable_product_configuration(document)
        for step in document["steps"]:
            if (
                not isinstance(step.get("check_ident"), str)
                or not step["check_ident"].strip()
                or not isinstance(step.get("parameters", {}), dict)
                or (
                    "required" in step
                    and (
                        not isinstance(step["required"], (bool, int))
                        or step["required"] not in (0, 1)
                    )
                )
            ):
                raise ValueError("invalid check structure")
        description = document["description"]
        if (
            not isinstance(description, str)
            or not description.strip()
            or description != description.strip()
            or len(description) > 500
            or len(source_path) > 500
        ):
            raise ValueError
    except Exception as exc:
        raise CatalogError(
            "definition_unavailable",
            "Product definition '{}' is unavailable or invalid.".format(
                product_ident
            ),
        ) from exc
    return DefinitionSnapshot(
        product_ident=canonical_ident,
        description=description,
        digest=hashlib.sha256(payload).hexdigest(),
        document=document,
        source_path=source_path,
    )


def _invalid_json_constant(value):
    raise ValueError("Non-finite JSON number: {}".format(value))


def _validate_json_strings(document):
    """JSONB requires Unicode strings without NUL or unpaired surrogates."""

    pending = [document]
    while pending:
        value = pending.pop()
        if isinstance(value, str):
            if "\x00" in value:
                raise ValueError("NUL is not supported in JSONB strings")
            value.encode("utf-8", errors="strict")
        elif isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)


def _finite_json_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite JSON number: {}".format(value))
    return number


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: {}".format(key))
        result[key] = value
    return result
