"""Product catalog import and coverage query facade."""

from .contracts import CatalogSyncResult
from .contracts import ProductCoverage
from .coverage import get_product_coverage
from .coverage import get_remaining_aoi_codes
from .coverage import list_current_product_coverage
from .definitions import snapshot_definition_for_job
from .errors import CatalogError
from .manifest import load_catalog_manifest
from .manifest import load_definition_snapshot
from .sync import synchronize_product_catalog

__all__ = [
    "CatalogError",
    "CatalogSyncResult",
    "ProductCoverage",
    "get_product_coverage",
    "get_remaining_aoi_codes",
    "list_current_product_coverage",
    "load_catalog_manifest",
    "load_definition_snapshot",
    "snapshot_definition_for_job",
    "synchronize_product_catalog",
]
