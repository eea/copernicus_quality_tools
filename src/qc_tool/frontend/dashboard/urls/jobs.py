"""QC job setup, lifecycle, history, and artifact routes."""

from qc_tool.frontend.dashboard.urls._helpers import protected_path
from qc_tool.frontend.dashboard.views.jobs.artifacts import get_attachment
from qc_tool.frontend.dashboard.views.jobs.artifacts import (
    get_combined_job_log,
)
from qc_tool.frontend.dashboard.views.jobs.artifacts import get_pdf_report
from qc_tool.frontend.dashboard.views.jobs.creation import create_job
from qc_tool.frontend.dashboard.views.jobs.history import get_job_history_json
from qc_tool.frontend.dashboard.views.jobs.mutations import job_delete
from qc_tool.frontend.dashboard.views.jobs.results import get_job_report
from qc_tool.frontend.dashboard.views.jobs.setup import get_job_info
from qc_tool.frontend.dashboard.views.jobs.setup import setup_job
from qc_tool.frontend.dashboard.views.jobs.status import update_job


urlpatterns = [
    protected_path("setup_job", setup_job, name="setup_job"),
    protected_path("create_job", create_job, name="create_job"),
    protected_path("job/delete/", job_delete, name="job_delete"),
    protected_path(
        "job/update/<uuid:job_uuid>/",
        update_job,
        name="update_job",
    ),
    protected_path(
        "data/job_history/<int:delivery_id>/",
        get_job_history_json,
        name="job_history_json",
    ),
    protected_path(
        "data/job_info/<product_ident>/",
        get_job_info,
        name="job_info_json",
    ),
    protected_path(
        "data/report/<uuid:job_uuid>/report.pdf",
        get_pdf_report,
        name="job_report_pdf",
    ),
    protected_path(
        "data/report/<uuid:job_uuid>/report.json",
        get_job_report,
        name="job_report_json",
    ),
    protected_path(
        "data/log/<uuid:job_uuid>/log.txt",
        get_combined_job_log,
        name="job_combined_log",
    ),
    protected_path(
        "attachment/<uuid:job_uuid>/<attachment_filename>/",
        get_attachment,
        name="get_attachment",
    ),
]
