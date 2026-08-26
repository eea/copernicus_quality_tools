"""JSON endpoint for the server-backed delivery table."""

from django.http import JsonResponse

from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard.services.deliveries import (
    count_delivery_statuses,
)
from qc_tool.frontend.dashboard.services.deliveries import (
    InvalidDeliveryStatus,
)
from qc_tool.frontend.dashboard.services.deliveries import summarize_deliveries
from qc_tool.frontend.dashboard.services.deliveries.listing import (
    decode_filter_mapping,
)
from qc_tool.frontend.dashboard.services.deliveries.listing import (
    query_deliveries,
)

from .links import add_delivery_links
from .parameters import delivery_list_parameters


def get_deliveries_json(request):
    """Return visible deliveries and access-scoped workspace summaries."""

    try:
        parameters = delivery_list_parameters(request, default_limit=100)
    except InvalidDeliveryStatus as exc:
        return JsonResponse(
            {
                "status": "error",
                "code": "invalid_delivery_status",
                "message": str(exc),
            },
            status=400,
        )

    account_access = access_for_request(request)
    total, data = query_deliveries(
        request.user,
        include_capabilities=True,
        account_access=account_access,
        **parameters.as_query_kwargs(),
    )
    add_delivery_links(data)

    filter_mapping = (
        decode_filter_mapping(parameters.filter_expression)
        if parameters.filter_expression
        else {}
    )
    status_counts = count_delivery_statuses(
        account_access,
        search=parameters.search,
        product_description=filter_mapping.get("product_description"),
        aoi_code=filter_mapping.get("aoi_code"),
    )
    return JsonResponse(
        {
            "total": total,
            "rows": data,
            "summary": summarize_deliveries(account_access).as_dict(),
            "status_counts": status_counts.as_dict(),
            "active_status": parameters.delivery_status.value,
        }
    )
