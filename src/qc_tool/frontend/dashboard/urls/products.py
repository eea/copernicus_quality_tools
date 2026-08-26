"""Product catalog routes."""

from qc_tool.frontend.dashboard.urls._helpers import protected_path
from qc_tool.frontend.dashboard.views.products import get_product_definition
from qc_tool.frontend.dashboard.views.products import (
    get_product_descriptions_dropdown,
)
from qc_tool.frontend.dashboard.views.products import get_product_list
from qc_tool.frontend.dashboard.views.products import product_detail
from qc_tool.frontend.dashboard.views.products import products


urlpatterns = [
    protected_path("products/", products, name="products"),
    protected_path(
        "products/list/",
        get_product_list,
        name="product_list_json",
    ),
    protected_path(
        "products/<str:product_ident>/",
        product_detail,
        name="product_detail",
    ),
    protected_path(
        "data/product_definition/<product_ident>/",
        get_product_definition,
        name="product_definition_json",
    ),
    protected_path(
        "data/product_descriptions/",
        get_product_descriptions_dropdown,
        name="product_descriptions_dropdown",
    ),
]
