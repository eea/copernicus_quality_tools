"""Workspace configuration routes."""

from qc_tool.frontend.dashboard.urls._helpers import protected_path
from qc_tool.frontend.dashboard.views.configuration import announcement


urlpatterns = [
    protected_path("announcement/", announcement, name="announcement"),
]
