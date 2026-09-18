"""Authenticated compatibility routes for superseded paths.

Named application routes always resolve to the current area hierarchy. These
aliases are isolated so they can be removed after their deprecation windows
without touching the canonical URL modules. Browser pages redirect in one hop;
the legacy product-list data route preserves its original JSON response.
"""

from django.views.generic import RedirectView

from qc_tool.frontend.dashboard.urls._helpers import protected_path
from qc_tool.frontend.dashboard.views.products.data import get_product_list


def _redirect_to(route_name):
    return RedirectView.as_view(
        pattern_name=route_name,
        permanent=True,
        query_string=True,
        http_method_names=("get", "head", "options"),
    )


urlpatterns = [
    protected_path(
        "submissions/",
        _redirect_to("submission_queue"),
        name="legacy_submission_queue",
    ),
    protected_path(
        "upload/",
        _redirect_to("file_upload"),
        name="legacy_file_upload",
    ),
    protected_path(
        "setup_job",
        _redirect_to("setup_job"),
        name="legacy_setup_job",
    ),
    protected_path(
        "boundaries_upload/",
        _redirect_to("boundaries_upload"),
        name="legacy_boundaries_upload",
    ),
    protected_path(
        "job_history/<int:delivery_id>/",
        _redirect_to("job_history"),
        name="legacy_job_history",
    ),
    protected_path(
        "deliveries/job_history/<int:delivery_id>/",
        _redirect_to("job_history"),
        name="legacy_delivery_job_history",
    ),
    protected_path(
        "result/<uuid:job_uuid>",
        _redirect_to("show_result"),
        name="legacy_show_result",
    ),
    protected_path(
        "deliveries/result/<uuid:job_uuid>",
        _redirect_to("show_result"),
        name="legacy_delivery_show_result",
    ),
    protected_path(
        "data/product_list/",
        get_product_list,
        name="legacy_product_list_json",
    ),
]
