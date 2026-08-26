"""Compatibility exports for the feature-owned dashboard views.

New routes and tests should import the owning module directly.  These exports
keep older integrations working while the application migrates away from the
former monolithic ``dashboard.views`` module.
"""

from qc_tool.frontend.dashboard.views.api_access import api_create_job
from qc_tool.frontend.dashboard.views.api_access import api_delivery_list
from qc_tool.frontend.dashboard.views.api_access import api_homepage
from qc_tool.frontend.dashboard.views.api_access import api_job_history
from qc_tool.frontend.dashboard.views.api_access import api_job_result
from qc_tool.frontend.dashboard.views.api_access import api_job_result_pdf
from qc_tool.frontend.dashboard.views.api_access import api_openapi_json
from qc_tool.frontend.dashboard.views.api_access import api_product_info
from qc_tool.frontend.dashboard.views.api_access import api_product_list
from qc_tool.frontend.dashboard.views.api_access import api_register_delivery
from qc_tool.frontend.dashboard.views.api_access import api_register_delivery_s3
from qc_tool.frontend.dashboard.views.api_access import api_submit_delivery_to_eea
from qc_tool.frontend.dashboard.views.boundaries import boundaries
from qc_tool.frontend.dashboard.views.boundaries import boundaries_upload
from qc_tool.frontend.dashboard.views.boundaries import boundaries_upload_page
from qc_tool.frontend.dashboard.views.boundaries import get_boundaries_json
from qc_tool.frontend.dashboard.views.configuration import announcement
from qc_tool.frontend.dashboard.views.configuration import update_announcement
from qc_tool.frontend.dashboard.views.deliveries.actions.deletion import (
    delivery_delete,
)
from qc_tool.frontend.dashboard.views.deliveries.actions.submissions import (
    submit_deliveries_to_eea_batch,
)
from qc_tool.frontend.dashboard.views.deliveries.actions.submissions import (
    submit_delivery_to_eea,
)
from qc_tool.frontend.dashboard.views.deliveries.files import download_delivery_file
from qc_tool.frontend.dashboard.views.deliveries.listing import (
    export_deliveries_excel,
)
from qc_tool.frontend.dashboard.views.deliveries.listing import get_deliveries_json
from qc_tool.frontend.dashboard.services.deliveries.listing import (
    parse_filter,
    query_deliveries,
)
from qc_tool.frontend.dashboard.views.deliveries.pages import deliveries
from qc_tool.frontend.dashboard.views.jobs import create_job
from qc_tool.frontend.dashboard.views.jobs import get_attachment
from qc_tool.frontend.dashboard.views.jobs import get_combined_job_log
from qc_tool.frontend.dashboard.views.jobs import get_job_history_json
from qc_tool.frontend.dashboard.views.jobs import get_job_info
from qc_tool.frontend.dashboard.views.jobs import get_job_report
from qc_tool.frontend.dashboard.views.jobs import get_pdf_report
from qc_tool.frontend.dashboard.views.jobs import get_result
from qc_tool.frontend.dashboard.views.jobs import job_delete
from qc_tool.frontend.dashboard.views.jobs import job_history_page
from qc_tool.frontend.dashboard.views.jobs import refresh_job_statuses
from qc_tool.frontend.dashboard.views.jobs import setup_job
from qc_tool.frontend.dashboard.views.jobs import update_job
from qc_tool.frontend.dashboard.views.overview import dashboard_home
from qc_tool.frontend.dashboard.views.products import get_product_definition
from qc_tool.frontend.dashboard.views.products import (
    get_product_descriptions_dropdown,
)
from qc_tool.frontend.dashboard.views.products import get_product_list
from qc_tool.frontend.dashboard.views.products import products
from qc_tool.frontend.dashboard.views.uploads import resumable_upload
from qc_tool.frontend.dashboard.views.uploads import resumable_upload_page
from qc_tool.frontend.dashboard.views.uploads import uploaded_delivery_file_exists
from qc_tool.frontend.dashboard.views.workers import pull_job


__all__ = tuple(name for name in globals() if not name.startswith("_"))
