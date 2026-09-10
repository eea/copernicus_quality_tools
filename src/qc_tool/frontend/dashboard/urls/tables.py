"""Application-wide table utilities with explicit route access policies."""

from qc_tool.frontend.dashboard.urls._helpers import protected_path
from qc_tool.frontend.dashboard.views.table_exports import table_export


urlpatterns = [protected_path("data/tables/export/", table_export, name="table_export")]
