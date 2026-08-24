"""Internal worker callback routes."""

from qc_tool.frontend.dashboard import views
from qc_tool.frontend.dashboard.urls._helpers import protected_path


urlpatterns = [
    protected_path("pull_job", views.pull_job, name="pull_job"),
]
