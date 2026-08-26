"""Delivery table JSON and spreadsheet endpoints."""

import io
import uuid
import openpyxl
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.http import JsonResponse
from django.urls import reverse
from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.jobs import normalize_job_uuid
from qc_tool.frontend.dashboard.services.deliveries import (
    InvalidDeliveryStatus,
)
from qc_tool.frontend.dashboard.services.deliveries import (
    count_delivery_statuses,
)
from qc_tool.frontend.dashboard.services.deliveries import parse_delivery_status
from qc_tool.frontend.dashboard.services.deliveries import summarize_deliveries
from qc_tool.frontend.dashboard.services.exports import spreadsheet_cell_value

from qc_tool.frontend.dashboard.services.deliveries.listing import (
    MAX_DELIVERY_OFFSET,
    MAX_DELIVERY_PAGE_SIZE,
    bounded_query_integer,
    decode_filter_mapping,
    query_deliveries,
)


def get_deliveries_json(request):
    """
    Returns a list of all deliveries for the current user.
    The deliveries are loaded from the dashboard_deliveries database table.
    The associated ZIP files are stored in <MEDIA_ROOT>/<username>/

    :param request:
    :return: list of deliveries with associated job information in JSON format
    """
    offset = bounded_query_integer(
        request.GET.get("offset"),
        default=0,
        minimum=0,
        maximum=MAX_DELIVERY_OFFSET,
    )
    limit = bounded_query_integer(
        request.GET.get("limit"),
        default=100,
        minimum=0,
        maximum=MAX_DELIVERY_PAGE_SIZE,
    )
    sort = request.GET.get("sort", "id")
    order = request.GET.get("order", "desc")
    filter = request.GET.get("filter", "")
    search = request.GET.get("search", "")
    try:
        delivery_status = parse_delivery_status(
            request.GET.get("delivery_status")
        )
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
        offset=offset,
        limit=limit,
        sort=sort,
        order=order,
        filter=filter,
        search=search,
        include_capabilities=True,
        account_access=account_access,
        delivery_status=delivery_status,
    )

    for item in data:
        item["job_history_url"] = reverse(
            "job_history",
            args=(item["id"],),
        )
        if item["last_job_uuid"]:
            # Raw SQLite cursors expose UUIDField values as compact text while
            # PostgreSQL exposes ``UUID`` objects. Canonicalise at this boundary
            # so both the JSON contract and Django's ``<uuid:...>`` route work
            # identically on every supported database.
            item["last_job_uuid"] = normalize_job_uuid(
                item["last_job_uuid"]
            )
            item["job_result_url"] = reverse(
                "show_result",
                args=(item["last_job_uuid"],),
            )
        else:
            item["job_result_url"] = None

    delivery_summary = summarize_deliveries(account_access)
    filter_mapping = decode_filter_mapping(filter) if filter else {}
    delivery_status_counts = count_delivery_statuses(
        account_access,
        search=search,
        product_description=filter_mapping.get("product_description"),
        aoi_code=filter_mapping.get("aoi_code"),
    )
    return JsonResponse(
        {
            "total": total,
            "rows": data,
            "summary": delivery_summary.as_dict(),
            "status_counts": delivery_status_counts.as_dict(),
            "active_status": delivery_status.value,
        }
    )


def export_deliveries_excel(request):
    """
    Exports deliveries (filtered/sorted like get_deliveries_json)
    into an Excel (.xlsx) file and returns it as a download.
    """
    # Same parameters as JSON endpoint
    offset = bounded_query_integer(
        request.GET.get("offset"),
        default=0,
        minimum=0,
        maximum=MAX_DELIVERY_OFFSET,
    )
    limit = bounded_query_integer(
        request.GET.get("limit"),
        default=1_000,
        minimum=0,
        maximum=MAX_DELIVERY_PAGE_SIZE,
    )
    sort = request.GET.get("sort", "id")
    order = request.GET.get("order", "desc")
    filter = request.GET.get("filter", "")
    search = request.GET.get("search", "")
    try:
        delivery_status = parse_delivery_status(
            request.GET.get("delivery_status")
        )
    except InvalidDeliveryStatus as exc:
        return HttpResponseBadRequest(str(exc))

    # Get data using your existing query function
    _, data = query_deliveries(
        request.user,
        offset=offset,
        limit=limit,
        sort=sort,
        order=order,
        filter=filter,
        search=search,
        delivery_status=delivery_status,
    )
    # Create a new Excel workbook
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Deliveries"

    if not data:
        ws.append(["No data found"])
    else:
        # Write header
        headers = list(data[0].keys())
        ws.append(headers)
        # Write rows in compatible format (e.g. convert UUIDs to strings)
        for row in data:
            formatted_row = []
            for col in headers:
                value = row.get(col, "")
                if isinstance(value, uuid.UUID):
                    value = str(value)
                formatted_row.append(spreadsheet_cell_value(value))
            ws.append(formatted_row)

    # Adjust column widths
    for col in ws.columns:
        max_length = max(len(str(cell.value or "")) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = min(max_length + 2, 60)

    # Save workbook to in-memory buffer
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = "attachment; filename=deliveries.xlsx"
    return response
