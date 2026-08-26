"""Orchestrate an access-scoped workspace dashboard snapshot."""

from qc_tool.frontend.dashboard.access.delivery_querysets import (
    visible_deliveries,
)

from .contracts import WorkspaceDashboard
from .limits import validate_item_limit
from .sections.activity import build_recent_activity
from .sections.coverage import build_coverage_segments
from .sections.delivery_summary import build_delivery_overview
from .sections.product_attention import build_product_attention


DEFAULT_ITEM_LIMIT = 5


def build_workspace_overview(
    account_access,
    *,
    recent_limit=DEFAULT_ITEM_LIMIT,
    product_limit=DEFAULT_ITEM_LIMIT,
):
    """Return bounded dashboard facts restricted to ``account_access``.

    The service intentionally avoids forecasts, target AOIs, trends, and token
    expiry because those concepts do not exist in the current data model.
    """

    validate_item_limit(recent_limit)
    validate_item_limit(product_limit)
    deliveries = visible_deliveries(account_access)
    summary = build_delivery_overview(deliveries)
    return WorkspaceDashboard(
        summary=summary,
        coverage=build_coverage_segments(summary),
        product_attention=build_product_attention(deliveries, product_limit),
        recent_activity=build_recent_activity(
            deliveries,
            account_access=account_access,
            limit=recent_limit,
        ),
    )
