"""Admin-owned boundary catalog and package-management routes.

Mount before Django's Admin catch-all. Existing reverse names point only to
these canonical Admin locations, including the structured data endpoints.
"""

from qc_tool.frontend.dashboard.urls._helpers import protected_path
from qc_tool.frontend.dashboard.views.boundaries import boundaries
from qc_tool.frontend.dashboard.views.boundaries import boundaries_upload
from qc_tool.frontend.dashboard.views.boundaries import boundaries_upload_page
from qc_tool.frontend.dashboard.views.boundaries import get_boundaries_json
from qc_tool.frontend.dashboard.views.table_exports import table_export
from qc_tool.frontend.dashboard.views.boundary_retention import retained_boundaries, retained_boundary_action


urlpatterns = [
    protected_path("", boundaries, name="boundaries"),
    protected_path("export/", table_export, name="boundaries_export"),
    protected_path("retained/", retained_boundaries, name="boundaries_retention"),
    protected_path("retained/action/", retained_boundary_action, name="boundaries_retention_action"),
    protected_path(
        "upload/",
        boundaries_upload_page,
        name="boundaries_upload",
    ),
    protected_path(
        "upload/data/",
        boundaries_upload,
        name="boundaries_upload_data",
    ),
    protected_path(
        "data/<boundary_type>/",
        get_boundaries_json,
        name="boundaries_json",
    ),
]
