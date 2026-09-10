"""Tabular downloads using the delivery list's access and workflow rules."""

from django.http import HttpResponseBadRequest

from qc_tool.frontend.dashboard.services.deliveries import InvalidDeliveryStatus
from qc_tool.frontend.dashboard.services.deliveries.listing import iter_deliveries
from qc_tool.frontend.dashboard.services.deliveries.listing import MAX_DELIVERY_PAGE_SIZE
from qc_tool.frontend.dashboard.services.deliveries.listing.workflows import InvalidDeliveryWorkflow
from qc_tool.frontend.dashboard.services.exports import (
    InvalidTableExport, export_format, select_export_columns, table_export_response,
)

from .parameters import delivery_list_parameters
from .workbook import DELIVERY_EXPORT_COLUMNS


def _delivery_export_rows(user, parameters):
    """Use the same filters and ordering as the table, without UI paging."""

    query = parameters.as_query_kwargs()
    query.pop("offset")
    query.pop("limit")
    return iter_deliveries(user, **query)


def export_deliveries_excel(request):
    """Keep the existing URL while using the application's export formats."""

    try:
        format = export_format(request.GET.get("format"))
        columns = select_export_columns(DELIVERY_EXPORT_COLUMNS, request.GET.get("columns"))
        parameters = delivery_list_parameters(request, default_limit=MAX_DELIVERY_PAGE_SIZE)
        rows = _delivery_export_rows(request.user, parameters)
    except (InvalidDeliveryStatus, InvalidDeliveryWorkflow, InvalidTableExport) as exc:
        return HttpResponseBadRequest(str(exc))

    return table_export_response(
        rows, columns,
        format=format, filename="deliveries", sheet_name="Deliveries",
    )
