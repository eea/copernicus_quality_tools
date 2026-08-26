"""Internal worker callback routes."""

from qc_tool.frontend.dashboard.urls._helpers import protected_path
from qc_tool.frontend.dashboard.views.workers import pull_job


urlpatterns = [
    protected_path("pull_job", pull_job, name="pull_job"),
]
