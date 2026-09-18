"""Product catalog routes."""

from qc_tool.frontend.dashboard.urls._helpers import protected_path
from qc_tool.frontend.dashboard.views.products import get_product_definition
from qc_tool.frontend.dashboard.views.products import (
    get_product_descriptions_dropdown,
)
from qc_tool.frontend.dashboard.views.products import get_product_list
from qc_tool.frontend.dashboard.views.products import product_detail
from qc_tool.frontend.dashboard.views.products import products
from qc_tool.frontend.dashboard.views.products.upload import product_upload, product_remove
from qc_tool.frontend.dashboard.views.products.plans import product_plan_edit
from qc_tool.frontend.dashboard.views.products.readiness import product_finalize


urlpatterns = [
    protected_path("products/", products, name="products"),
    protected_path("products/upload/", product_upload, name="product_upload"),
    protected_path("products/<str:product_ident>/remove/", product_remove, name="product_remove"),
    protected_path("products/<str:product_ident>/plans/<int:release_id>/", product_plan_edit, name="product_plan_edit"),
    protected_path("products/<str:product_ident>/finalize/", product_finalize, name="product_finalize"),
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
