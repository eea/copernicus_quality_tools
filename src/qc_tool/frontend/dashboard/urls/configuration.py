"""Workspace configuration routes."""

from qc_tool.frontend.dashboard.urls._helpers import protected_path
from qc_tool.frontend.dashboard.views.configuration import announcement
from qc_tool.frontend.dashboard.views.configuration import update_announcement


urlpatterns = [
    protected_path("announcement/", announcement, name="announcement"),
    protected_path(
        "announcement/update/",
        update_announcement,
        name="announcement_update",
    ),
]
