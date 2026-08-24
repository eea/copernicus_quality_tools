"""Object-level access policies for dashboard domain models."""

from qc_tool.frontend.dashboard.access.deliveries import can_view_delivery
from qc_tool.frontend.dashboard.access.deliveries import delivery_action_capabilities
from qc_tool.frontend.dashboard.access.deliveries import require_delivery_view
from qc_tool.frontend.dashboard.access.jobs import can_view_job
from qc_tool.frontend.dashboard.access.jobs import require_job_view

__all__ = [
    "can_view_delivery",
    "can_view_job",
    "delivery_action_capabilities",
    "require_delivery_view",
    "require_job_view",
]
