"""Public models for the versioned product catalog domain.

Import models from this package boundary.  Individual modules contain one
aggregate concept so catalog behavior can evolve without rebuilding a single
large model module.
"""

from .product import Product
from .product_aoi import ProductAOI
from .product_release import ProductRelease
from .product_release_definition import ProductReleaseDefinition
from .qc_definition import QcDefinition

__all__ = (
    "Product",
    "ProductAOI",
    "ProductRelease",
    "ProductReleaseDefinition",
    "QcDefinition",
)
