"""Bounds and supported values for catalog manifests."""

MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_RELEASES = 5_000
MAX_PRODUCT_UNITS_PER_RELEASE = 100_000
MAX_DEFINITIONS_PER_RELEASE = 100

NAMING_CHECK_SUFFIXES = (".naming", ".naming_pdf")
VALID_COVERAGE_STATES = frozenset(("unknown", "draft", "authoritative"))
