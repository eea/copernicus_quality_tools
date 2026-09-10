"""Validate definition directories and their explicitly declared AOI scope."""

from pathlib import Path

from qc_tool.aoi import normalize_aoi_code
from qc_tool.product_security import normalize_product_ident

from .errors import CatalogError
from .manifest.constants import MAX_AOIS_PER_RELEASE
from .manifest.constants import MAX_RELEASES
from .manifest.constants import NAMING_CHECK_SUFFIXES
from .manifest.coverage import extract_definition_aoi_codes
from .manifest.definitions import build_definition_snapshot
from .manifest.validation import invalid_manifest


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

    lists = []
    for step in definition.document["steps"]:
        if not step["check_ident"].endswith(NAMING_CHECK_SUFFIXES):
            continue
        parameters = step.get("parameters", {})
        if "aoi_codes" not in parameters:
            continue
        values = parameters["aoi_codes"]
        if not isinstance(values, list) or len(values) > MAX_AOIS_PER_RELEASE:
            raise invalid_manifest("definition aoi_codes must be a bounded list")
        if any(
            value != "*" and normalize_aoi_code(value) is None
            for value in values
        ):
            raise invalid_manifest("definition contains an invalid AOI")
        lists.append(values)
    if not lists or any(not values or "*" in values for values in lists):
        return {"state": "unknown"}
    extract_definition_aoi_codes(definition.document)
    return {"state": "draft", "source_definition": definition.product_ident}
