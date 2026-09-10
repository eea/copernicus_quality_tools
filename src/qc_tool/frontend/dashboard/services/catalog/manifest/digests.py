"""Stable content identities for immutable catalog releases."""

import hashlib
import json


def calculate_release_digest(
    *,
    product_ident,
    release_key,
    revision,
    description,
    coverage_state,
    definitions,
    primary_definition_ident,
    aoi_codes,
    source_kind="manifest",
):
    document = {
        "product_ident": product_ident,
        "release_key": release_key,
        "revision": revision,
        "description": description,
        "coverage_state": coverage_state,
        "definitions": [
            [definition.product_ident, definition.digest]
            for definition in definitions
        ],
        "primary_definition": primary_definition_ident,
        "aoi_codes": aoi_codes,
        "source_kind": source_kind,
    }
    encoded = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
