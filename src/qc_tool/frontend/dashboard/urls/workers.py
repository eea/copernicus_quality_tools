"""Internal worker callback routes."""

from qc_tool.frontend.dashboard.urls._helpers import protected_path
from qc_tool.frontend.dashboard.views.workers import pull_job, worker_maintenance


urlpatterns = [
    protected_path("pull_job", pull_job, name="pull_job"),
    protected_path("worker_maintenance", worker_maintenance, name="worker_maintenance"),
]
