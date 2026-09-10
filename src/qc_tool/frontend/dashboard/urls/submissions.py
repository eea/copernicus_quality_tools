"""Submitted delivery tracking and review routes."""

from ._helpers import protected_path
from qc_tool.frontend.dashboard.views.submissions import (
    submission_file,
    submission_queue,
    submission_review,
)


urlpatterns = [
    protected_path("submissions/", submission_queue, name="submission_queue"),
    protected_path(
        "submissions/<uuid:submission_id>/", submission_review,
        name="submission_review",
    ),
    protected_path(
        "submissions/<uuid:submission_id>/files/<path:filename>", submission_file,
        name="submission_file",
    ),
]
