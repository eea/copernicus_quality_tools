"""Boundary catalog and package-management routes."""

from qc_tool.frontend.dashboard.urls._helpers import protected_path
from qc_tool.frontend.dashboard.views.boundaries import boundaries
from qc_tool.frontend.dashboard.views.boundaries import boundaries_upload
from qc_tool.frontend.dashboard.views.boundaries import boundaries_upload_page
from qc_tool.frontend.dashboard.views.boundaries import get_boundaries_json


urlpatterns = [
    protected_path("boundaries/", boundaries, name="boundaries"),
    protected_path(
        "boundaries_upload/",
        boundaries_upload_page,
        name="boundaries_upload",
    ),
    protected_path(
        "data/boundaries/upload/",
        boundaries_upload,
        name="boundaries_upload_data",
    ),
    protected_path(
        "data/boundaries/<boundary_type>/",
        get_boundaries_json,
        name="boundaries_json",
    ),
]
