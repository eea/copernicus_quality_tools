"""Human-facing dashboard pages and browser downloads."""

from qc_tool.frontend.dashboard import views
from qc_tool.frontend.dashboard.urls._helpers import protected_path


urlpatterns = [
    protected_path("", views.deliveries, name="deliveries"),
    protected_path(
        "data/delivery/export/",
        views.export_deliveries_excel,
        name="export_deliveries_excel",
    ),
    protected_path(
        "data/delivery/file/<int:delivery_id>/",
        views.download_delivery_file,
        name="download_delivery_file",
    ),
    protected_path(
        "data/report/<uuid:job_uuid>/report.pdf",
        views.get_pdf_report,
        name="job_report_pdf",
    ),
    protected_path(
        "data/log/<uuid:job_uuid>/log.txt",
        views.get_combined_job_log,
        name="job_combined_log",
    ),
    protected_path("upload/", views.resumable_upload_page, name="file_upload"),
    protected_path(
        "job_history/<int:delivery_id>/",
        views.job_history_page,
        name="job_history",
    ),
    protected_path("boundaries/", views.boundaries, name="boundaries"),
    protected_path(
        "boundaries_upload/",
        views.boundaries_upload_page,
        name="boundaries_upload",
    ),
    protected_path("setup_job", views.setup_job, name="setup_job"),
    protected_path(
        "result/<uuid:job_uuid>",
        views.get_result,
        name="show_result",
    ),
    protected_path(
        "attachment/<uuid:job_uuid>/<attachment_filename>/",
        views.get_attachment,
        name="get_attachment",
    ),
    protected_path("announcement/", views.announcement, name="announcement"),
    protected_path(
        "announcement/update/",
        views.update_announcement,
        name="announcement_update",
    ),
]
