"""Submitted delivery tracking and review routes."""

from django.views.generic import RedirectView

from ._helpers import protected_path
from qc_tool.frontend.dashboard.views.submissions import (
    submission_file,
    submission_queue,
    submission_bulk_approve,
    submission_review,
)


urlpatterns = [
    protected_path("products/submissions", submission_queue, name="submission_queue"),
    protected_path("products/submissions/approve", submission_bulk_approve, name="submission_bulk_approve"),
    protected_path(
        "products/submissions/",
        RedirectView.as_view(
            pattern_name="submission_queue", permanent=True, query_string=True,
            http_method_names=("get", "head", "options"),
        ),
        name="submission_queue_slash",
    ),
    protected_path(
        "submissions/<uuid:submission_id>/", submission_review,
        name="submission_review",
    ),
    protected_path(
        "submissions/<uuid:submission_id>/files/<path:filename>", submission_file,
        name="submission_file",
    ),
]
