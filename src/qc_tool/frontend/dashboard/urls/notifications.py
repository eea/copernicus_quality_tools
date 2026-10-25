"""Admin-only notification preview and publication endpoints."""

from qc_tool.frontend.dashboard.urls._helpers import protected_path
from qc_tool.frontend.dashboard.views.admin_notifications import (
    notifications,
    update_announcement,
)


urlpatterns = [
    protected_path("", notifications, name="admin_notifications"),
    protected_path("update/", update_announcement, name="announcement_update"),
]
