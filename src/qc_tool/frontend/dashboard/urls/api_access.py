"""Public API documentation and API-key-authenticated routes."""

from qc_tool.frontend.dashboard.urls._helpers import protected_path
from qc_tool.frontend.dashboard.views.api_access.deliveries import api_delivery_list
from qc_tool.frontend.dashboard.views.api_access.deliveries import (
    api_register_delivery,
)
from qc_tool.frontend.dashboard.views.api_access.deliveries import (
    api_register_delivery_s3,
)
from qc_tool.frontend.dashboard.views.api_access.documentation import api_homepage
from qc_tool.frontend.dashboard.views.api_access.documentation import (
    api_openapi_json,
)
from qc_tool.frontend.dashboard.views.api_access.jobs import api_create_job
from qc_tool.frontend.dashboard.views.api_access.jobs import api_job_history
from qc_tool.frontend.dashboard.views.api_access.jobs import api_job_result
from qc_tool.frontend.dashboard.views.api_access.jobs import api_job_result_pdf
from qc_tool.frontend.dashboard.views.api_access.products import api_product_info
from qc_tool.frontend.dashboard.views.api_access.products import api_product_list
from qc_tool.frontend.dashboard.views.api_access.submissions import (
    api_submit_delivery_to_eea,
)


urlpatterns = [
    protected_path("api/", api_homepage, name="api_homepage"),
    protected_path(
        "api/openapi.json",
        api_openapi_json,
        name="api_openapi_json",
    ),
    protected_path(
        "api/register-delivery",
        api_register_delivery,
        name="api_register_delivery",
    ),
    protected_path(
        "api/register-delivery-s3",
        api_register_delivery_s3,
        name="api_register_delivery_s3",
    ),
    protected_path(
        "api/delivery-list",
        api_delivery_list,
        name="api_delivery_list",
    ),
    protected_path(
        "api/product-list",
        api_product_list,
        name="api_product_list",
    ),
    protected_path(
        "api/product-info/<product_ident>",
        api_product_info,
        name="api_product_info",
    ),
    protected_path("api/create-job", api_create_job, name="api_create_job"),
    protected_path(
        "api/job-result/<uuid:job_uuid>",
        api_job_result,
        name="api_job_result",
    ),
    protected_path(
        "api/job-result-pdf/<uuid:job_uuid>",
        api_job_result_pdf,
        name="api_job_result_pdf",
    ),
    protected_path(
        "api/job-history/<int:delivery_id>",
        api_job_history,
        name="api_job_history",
    ),
    protected_path(
        "api/submit-delivery-to-eea",
        api_submit_delivery_to_eea,
        name="api_submit_delivery_to_eea",
    ),
]
