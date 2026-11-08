"""Actions for known job setup failures, without exposing diagnostic details."""

from django.urls import reverse

from qc_tool.common import JOB_ERROR
from qc_tool.jobs.failures import BOUNDARY_UNAVAILABLE_MESSAGE


def setup_failure_outcome(report, status, account_access):
    if status != JOB_ERROR or report.get("error_code") != "boundary_generation_unavailable":
        return None
    outcome = {"title": "QC could not start", "message": BOUNDARY_UNAVAILABLE_MESSAGE,
               "tone": "warning", "icon": "alert-triangle"}
    if account_access.is_administrator:
        outcome["action"] = {"label": "Configure boundary data", "url": reverse("boundaries")}
    return outcome
