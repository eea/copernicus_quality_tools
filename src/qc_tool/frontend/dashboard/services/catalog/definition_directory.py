"""Validate definition directories and their explicitly declared product unit scope."""

from pathlib import Path

from qc_tool.product_security import normalize_product_ident

from .errors import CatalogError
from .manifest.constants import MAX_RELEASES
from .manifest.coverage import extract_definition_product_unit_codes, naming_unit_scopes
from .manifest.definitions import build_definition_snapshot


def read_definition_directories(directories):
    """Read all sources before writes; ambiguous identifiers fail as a unit."""

    paths = {}
    for directory in directories:
        root = Path(directory)
        if not root.is_dir():
            raise CatalogError("definition_directory_unavailable", str(root))
        try:
            candidates = sorted(root.glob("*.json"))
            for path in candidates:
                ident = normalize_product_ident(path.stem)
                if ident is None:
                    raise CatalogError(
                        "invalid_definition_ident",
                        "Invalid filename: {}".format(path.name),
                    )
                if ident in paths:
                    raise CatalogError(
                        "duplicate_definition_ident",
                        "Definition '{}' occurs more than once in the import.".format(
                            ident
                        ),
                    )
                paths[ident] = path
                if len(paths) > MAX_RELEASES:
                    raise CatalogError(
                        "too_many_definitions", "Import exceeds the definition limit."
                    )
        except OSError as exc:
            raise CatalogError("definition_directory_unavailable", str(root)) from exc
    if not paths:
        raise CatalogError(
            "empty_definition_directory", "No JSON definitions were found."
        )
    return tuple(
        build_definition_snapshot(ident, locate_definition=paths.__getitem__)
        for ident in sorted(paths)
    )


def declared_coverage(definition):
    """Finite naming values are candidates, never automatic business approval."""

    document = definition.document
    scopes, _declared, unbounded = naming_unit_scopes(document)
    explicit = any(key in document for key in ("product_units", "product_unit_codes", "aoi_codes"))
    if not explicit and (not scopes or unbounded):
        return {"state": "unknown"}
    extract_definition_product_unit_codes(document)
    return {"state": "draft", "source_definition": definition.product_ident}
