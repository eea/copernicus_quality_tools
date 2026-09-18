"""Stable public facade for product browser views."""

from qc_tool.frontend.accounts.services.products import (
    available_product_descriptions,
)
from qc_tool.frontend.accounts.services.products import ProductCatalogUnavailable

from .catalog import render_product_catalog
from .catalog import workspace_product_catalog
from .data import get_product_definition
from .data import get_product_descriptions_dropdown
from .data import get_product_list
from .details import product_detail


def _workspace_product_catalog():
    """Compatibility facade retaining the established test/extension seam."""

    return workspace_product_catalog(available_product_descriptions)


def products(request):
    return render_product_catalog(request)


__all__ = [
    "ProductCatalogUnavailable",
    "_workspace_product_catalog",
    "available_product_descriptions",
    "get_product_definition",
    "get_product_descriptions_dropdown",
    "get_product_list",
    "product_detail",
    "products",
]
