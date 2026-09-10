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
from qc_tool.frontend.dashboard.services.deliveries.listing.workflows import (
    DeliveryWorkflow, parse_delivery_workflow,
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
    delivery_view: object

    def as_query_kwargs(self):
        return {
            "offset": self.offset,
            "limit": self.limit,
            "sort": self.sort,
            "order": self.order,
            "filter": self.filter_expression,
            "search": self.search,
            "delivery_status": self.delivery_status,
            "delivery_view": self.delivery_view,
        }


def delivery_list_parameters(request, *, default_limit):
    """Parse and bound the parameters shared by JSON and Excel endpoints."""

    status = parse_delivery_status(request.GET.get("delivery_status"))
    view_value = request.GET.get("delivery_view")
    if not view_value:
        # Existing bookmarked leaf-status links remain valid across the full
        # list. The new working view is the default only without an override.
        view_value = (
            DeliveryWorkflow.ALL if request.GET.get("delivery_status")
            else DeliveryWorkflow.ACTION_REQUIRED
        )
    view = parse_delivery_workflow(view_value)
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
        sort=request.GET.get("sort", "priority"),
        order=request.GET.get("order", "desc"),
        filter_expression=request.GET.get("filter", ""),
        search=request.GET.get("search", ""),
        delivery_status=status,
        delivery_view=view,
    )
