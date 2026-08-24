"""Public API documentation and API-key-authenticated operations."""

from qc_tool.frontend.dashboard import views
from qc_tool.frontend.dashboard.urls._helpers import protected_path


urlpatterns = [
    protected_path("api/", views.api_homepage, name="api_homepage"),
    protected_path(
        "api/openapi.json",
        views.api_openapi_json,
        name="api_openapi_json",
    ),
    protected_path(
        "api/register-delivery",
        views.api_register_delivery,
        name="api_register_delivery",
    ),
    protected_path(
        "api/register-delivery-s3",
        views.api_register_delivery_s3,
        name="api_register_delivery_s3",
    ),
    protected_path(
        "api/delivery-list",
        views.api_delivery_list,
        name="api_delivery_list",
    ),
    protected_path(
        "api/product-list",
        views.api_product_list,
        name="api_product_list",
    ),
    protected_path(
        "api/product-info/<product_ident>",
        views.api_product_info,
        name="api_product_info",
    ),
    protected_path(
        "api/create-job",
        views.api_create_job,
        name="api_create_job",
    ),
    protected_path(
        "api/job-result/<uuid:job_uuid>",
        views.api_job_result,
        name="api_job_result",
    ),
    protected_path(
        "api/job-result-pdf/<uuid:job_uuid>",
        views.api_job_result_pdf,
        name="api_job_result_pdf",
    ),
    protected_path(
        "api/job-history/<int:delivery_id>",
        views.api_job_history,
        name="api_job_history",
    ),
    protected_path(
        "api/submit-delivery-to-eea",
        views.api_submit_delivery_to_eea,
        name="api_submit_delivery_to_eea",
    ),
]
