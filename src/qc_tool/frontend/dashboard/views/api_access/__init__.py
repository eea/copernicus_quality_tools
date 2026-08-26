"""Compatibility exports for the API access view package."""

from qc_tool.frontend.dashboard.views.api_access.deliveries import (
    api_delivery_list,
)
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


__all__ = tuple(name for name in globals() if name.startswith("api_"))
