"""Internal worker callback routes."""

from qc_tool.common import create_worker_token
from qc_tool.frontend.dashboard import views
from qc_tool.frontend.dashboard.urls._helpers import protected_path


urlpatterns = [
    protected_path("pull_job", views.pull_job, name="pull_job"),
]

# Preserve the existing worker-token bootstrap behavior until worker credentials
# move to deployment configuration.
create_worker_token()
