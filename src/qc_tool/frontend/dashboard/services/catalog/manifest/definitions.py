"""Validated snapshots of executable QC definitions."""

import hashlib
import json

from qc_tool.product_security import validate_executable_product_configuration
from qc_tool.product_security import normalize_product_ident

from ..contracts import DefinitionSnapshot
from ..errors import CatalogError


def build_definition_snapshot(product_ident, *, locate_definition):
    canonical_ident = normalize_product_ident(product_ident)
    if canonical_ident is None:
        raise CatalogError(
            "definition_unavailable",
            "The product definition identifier is invalid.",
        )
    try:
        path = locate_definition(canonical_ident)
        payload = path.read_bytes()
        document = json.loads(payload.decode("utf-8"))
        validate_executable_product_configuration(document)
        description = document["description"]
        if not isinstance(description, str) or not description.strip():
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
        source_path=str(path),
    )
