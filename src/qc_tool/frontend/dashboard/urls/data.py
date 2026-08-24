"""Session-authenticated JSON and mutation endpoints used by the dashboard."""

from qc_tool.frontend.dashboard import views
from qc_tool.frontend.dashboard.urls._helpers import protected_path


urlpatterns = [
    protected_path(
        "data/delivery/list/",
        views.get_deliveries_json,
        name="deliveries_json",
    ),
    protected_path(
        "data/job_history/<int:delivery_id>/",
        views.get_job_history_json,
        name="job_history_json",
    ),
    protected_path(
        "delivery/delete/",
        views.delivery_delete,
        name="delivery_delete",
    ),
    protected_path(
        "delivery/submit/",
        views.submit_delivery_to_eea,
        name="delivery_submit",
    ),
    protected_path(
        "delivery/submit_batch/",
        views.submit_deliveries_to_eea_batch,
        name="delivery_submit_batch",
    ),
    protected_path(
        "data/job_info/<product_ident>/",
        views.get_job_info,
        name="job_info_json",
    ),
    protected_path(
        "data/product_definition/<product_ident>/",
        views.get_product_definition,
        name="product_definition_json",
    ),
    protected_path(
        "data/product_list/",
        views.get_product_list,
        name="product_list_json",
    ),
    protected_path(
        "data/product_descriptions/",
        views.get_product_descriptions_dropdown,
        name="product_descriptions_dropdown",
    ),
    protected_path(
        "data/report/<uuid:job_uuid>/report.json",
        views.get_job_report,
        name="job_report_json",
    ),
    protected_path(
        "resumable_upload/",
        views.resumable_upload,
        name="resumable_upload",
    ),
    protected_path("job/delete/", views.job_delete, name="job_delete"),
    protected_path(
        "job/update/<uuid:job_uuid>/",
        views.update_job,
        name="update_job",
    ),
    protected_path(
        "data/boundaries/upload/",
        views.boundaries_upload,
        name="boundaries_upload_data",
    ),
    protected_path(
        "data/boundaries/<boundary_type>/",
        views.get_boundaries_json,
        name="boundaries_json",
    ),
    protected_path("create_job", views.create_job, name="create_job"),
]
