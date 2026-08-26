"""API delivery-list endpoint behavior."""

from django.http import JsonResponse


def list_deliveries(
    request,
    *,
    max_offset,
    max_page_size,
    parse_bounded_integer,
    query_delivery_rows,
    endpoint_logger,
):
    """Return one bounded page of deliveries visible to the API account."""
    user = request.api_user
    offset = parse_bounded_integer(
        request.GET.get("offset"),
        default=0,
        minimum=0,
        maximum=max_offset,
    )
    limit = parse_bounded_integer(
        request.GET.get("limit"),
        default=20,
        minimum=1,
        maximum=max_page_size,
    )

    sort = request.GET.get("sort", "id")
    order = request.GET.get("order", "desc")
    # Filter and search are intentionally ignored by the API; the UI uses
    # those query concepts separately.
    filter_value = ""
    search = ""

    total, data = query_delivery_rows(
        user,
        offset=offset,
        limit=limit,
        sort=sort,
        order=order,
        filter=filter_value,
        search=search,
        account_access=request.api_access,
    )
    endpoint_logger.debug("List of deliveries successfully obtained.")

    next_offset = 0 if len(data) < limit else offset + limit
    response_data = {
        "status": "ok",
        "message": "list of deliveries successfully obtained",
        "total": total,
        "offset": offset,
        "limit": limit,
        "next_offset": next_offset,
        "deliveries": data,
    }
    return JsonResponse(response_data, safe=False)
