"""Compatibility exports for browser-facing QC job views.

The implementation is split by HTTP responsibility so job setup, history,
results, artifacts, and status polling can evolve independently.
Importing views from this package keeps the former
``dashboard.views.jobs`` API stable for routes and integrations.
"""

from qc_tool.frontend.dashboard.views.jobs.artifacts import get_attachment
from qc_tool.frontend.dashboard.views.jobs.artifacts import (
    get_combined_job_log,
)
from qc_tool.frontend.dashboard.views.jobs.artifacts import get_pdf_report
from qc_tool.frontend.dashboard.views.jobs.creation import create_job
from qc_tool.frontend.dashboard.views.jobs.history import get_job_history_json
from qc_tool.frontend.dashboard.views.jobs.history import job_history_page
from qc_tool.frontend.dashboard.views.jobs.results import get_job_report
from qc_tool.frontend.dashboard.views.jobs.results import get_result
from qc_tool.frontend.dashboard.views.jobs.setup import get_job_info
from qc_tool.frontend.dashboard.views.jobs.setup import setup_job
from qc_tool.frontend.dashboard.views.jobs.status import (
    CHECK_RUNNING_JOB_DELAY,
)
from qc_tool.frontend.dashboard.views.jobs.status import refresh_job_statuses
from qc_tool.frontend.dashboard.views.jobs.status import update_job


__all__ = (
    "CHECK_RUNNING_JOB_DELAY",
    "create_job",
    "get_attachment",
    "get_combined_job_log",
    "get_job_history_json",
    "get_job_info",
    "get_job_report",
    "get_pdf_report",
    "get_result",
    "job_history_page",
    "refresh_job_statuses",
    "setup_job",
    "update_job",
)
