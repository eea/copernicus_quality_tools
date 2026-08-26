"""Browser upload routes."""

from qc_tool.frontend.dashboard.urls._helpers import protected_path
from qc_tool.frontend.dashboard.views.uploads import resumable_upload
from qc_tool.frontend.dashboard.views.uploads import resumable_upload_page


urlpatterns = [
    protected_path("upload/", resumable_upload_page, name="file_upload"),
    protected_path(
        "resumable_upload/",
        resumable_upload,
        name="resumable_upload",
    ),
]
