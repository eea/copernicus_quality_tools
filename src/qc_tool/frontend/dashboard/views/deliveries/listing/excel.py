"""Spreadsheet endpoint for the access-scoped delivery list."""

from django.http import HttpResponse
from django.http import HttpResponseBadRequest

from qc_tool.frontend.dashboard.services.deliveries import (
    InvalidDeliveryStatus,
)
from qc_tool.frontend.dashboard.services.deliveries.listing import (
    query_deliveries,
)

from .parameters import delivery_list_parameters
from .workbook import delivery_workbook_bytes


def export_deliveries_excel(request):
    """Export deliveries with the same filtering and sorting as the UI list."""

    try:
        parameters = delivery_list_parameters(request, default_limit=1_000)
    except InvalidDeliveryStatus as exc:
        return HttpResponseBadRequest(str(exc))

    _, data = query_deliveries(
        request.user,
        **parameters.as_query_kwargs(),
    )
    response = HttpResponse(
        delivery_workbook_bytes(data),
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )
    response["Content-Disposition"] = "attachment; filename=deliveries.xlsx"
    return response
