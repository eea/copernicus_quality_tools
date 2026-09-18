"""Public, database-free product catalog manifest loader."""

from qc_tool.common import locate_product_definition

from .constants import MAX_PRODUCT_UNITS_PER_RELEASE
from .constants import MAX_MANIFEST_BYTES
from .constants import MAX_RELEASES
from .constants import NAMING_CHECK_SUFFIXES
from .constants import VALID_COVERAGE_STATES
from .definitions import build_definition_snapshot
from .parser import parse_manifest_document
from .reader import read_manifest_document


def load_definition_snapshot(product_ident):
    """Load and validate one exact executable definition revision."""

    return build_definition_snapshot(
        product_ident,
        locate_definition=locate_product_definition,
    )


def parse_catalog_manifest(document):
    """Validate an already decoded manifest document."""

    return parse_manifest_document(
        document,
        definition_loader=load_definition_snapshot,
    )


def load_catalog_manifest(path, *, maximum_bytes=MAX_MANIFEST_BYTES):
    """Return a fully validated immutable snapshot with no database access."""

    document = read_manifest_document(path, maximum_bytes=maximum_bytes)
    return parse_catalog_manifest(document)


__all__ = [
    "MAX_PRODUCT_UNITS_PER_RELEASE",
    "MAX_MANIFEST_BYTES",
    "MAX_RELEASES",
    "NAMING_CHECK_SUFFIXES",
    "VALID_COVERAGE_STATES",
    "load_catalog_manifest",
    "load_definition_snapshot",
    "parse_catalog_manifest",
]
