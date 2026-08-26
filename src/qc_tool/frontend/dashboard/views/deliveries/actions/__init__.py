"""Compatibility exports for delivery lifecycle HTTP actions.

The action implementations are grouped by responsibility.  This package keeps
the former ``views.deliveries.actions`` import path stable for URLs, tests, and
third-party integrations while new code can import the focused modules.
"""

from qc_tool.frontend.dashboard.services.submissions import submit_delivery

from .deletion import delivery_delete
from .submissions import _submission_disabled_response
from .submissions import submit_deliveries_to_eea_batch
from .submissions import submit_delivery_to_eea


__all__ = (
    "delivery_delete",
    "submit_deliveries_to_eea_batch",
    "submit_delivery_to_eea",
)
