"""Workspace overview routes."""

from qc_tool.frontend.dashboard.urls._helpers import protected_path
from qc_tool.frontend.dashboard.views.overview import dashboard_home


urlpatterns = [
    protected_path("", dashboard_home, name="dashboard_home"),
]
