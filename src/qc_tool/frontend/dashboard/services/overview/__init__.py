"""Access-scoped presentation data for the authenticated dashboard."""

from .contracts import ActivityItem
from .contracts import CoverageSegment
from .contracts import DeliveryOverview
from .contracts import ProductAttention
from .contracts import WorkspaceDashboard
from .service import build_workspace_overview


# Transitional alias for callers using the former service name.
build_workspace_dashboard = build_workspace_overview

__all__ = (
    "ActivityItem",
    "CoverageSegment",
    "DeliveryOverview",
    "ProductAttention",
    "WorkspaceDashboard",
    "build_workspace_dashboard",
    "build_workspace_overview",
)
