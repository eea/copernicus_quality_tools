"""Shared HTTP query parsing for delivery-list representations."""

from dataclasses import dataclass

from qc_tool.frontend.dashboard.services.deliveries import (
    parse_delivery_status,
)
from qc_tool.frontend.dashboard.services.deliveries.listing import (
    bounded_query_integer,
)
from qc_tool.frontend.dashboard.services.deliveries.listing import (
    MAX_DELIVERY_OFFSET,
)
from qc_tool.frontend.dashboard.services.deliveries.listing import (
    MAX_DELIVERY_PAGE_SIZE,
)


@dataclass(frozen=True)
class DeliveryListParameters:
    offset: int
    limit: int
    sort: str
    order: str
    filter_expression: str
    search: str
    delivery_status: object

    def as_query_kwargs(self):
        return {
            "offset": self.offset,
            "limit": self.limit,
            "sort": self.sort,
            "order": self.order,
            "filter": self.filter_expression,
            "search": self.search,
            "delivery_status": self.delivery_status,
        }


def delivery_list_parameters(request, *, default_limit):
    """Parse and bound the parameters shared by JSON and Excel endpoints."""

    return DeliveryListParameters(
        offset=bounded_query_integer(
            request.GET.get("offset"),
            default=0,
            minimum=0,
            maximum=MAX_DELIVERY_OFFSET,
        ),
        limit=bounded_query_integer(
            request.GET.get("limit"),
            default=default_limit,
            minimum=0,
            maximum=MAX_DELIVERY_PAGE_SIZE,
        ),
        sort=request.GET.get("sort", "id"),
        order=request.GET.get("order", "desc"),
        filter_expression=request.GET.get("filter", ""),
        search=request.GET.get("search", ""),
        delivery_status=parse_delivery_status(
            request.GET.get("delivery_status")
        ),
    )
