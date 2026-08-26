"""Delivery workspace, query, export, and lifecycle routes."""

from qc_tool.frontend.dashboard.urls._helpers import protected_path
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
from qc_tool.frontend.dashboard.views.deliveries.pages import deliveries
from qc_tool.frontend.dashboard.views.jobs.history import job_history_page
from qc_tool.frontend.dashboard.views.jobs.results import get_result


urlpatterns = [
    protected_path("deliveries/", deliveries, name="deliveries"),
    protected_path(
        "deliveries/job_history/<int:delivery_id>/",
        job_history_page,
        name="job_history",
    ),
    protected_path(
        "deliveries/result/<uuid:job_uuid>",
        get_result,
        name="show_result",
    ),
    protected_path(
        "data/delivery/list/",
        get_deliveries_json,
        name="deliveries_json",
    ),
    protected_path(
        "data/delivery/export/",
        export_deliveries_excel,
        name="export_deliveries_excel",
    ),
    protected_path(
        "data/delivery/file/<int:delivery_id>/",
        download_delivery_file,
        name="download_delivery_file",
    ),
    protected_path("delivery/delete/", delivery_delete, name="delivery_delete"),
    protected_path(
        "delivery/submit/",
        submit_delivery_to_eea,
        name="delivery_submit",
    ),
    protected_path(
        "delivery/submit_batch/",
        submit_deliveries_to_eea_batch,
        name="delivery_submit_batch",
    ),
]
