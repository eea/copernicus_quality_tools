"""Delivery registration endpoint implementations."""

from qc_tool.frontend.dashboard.views.api_access.deliveries.registration.local import (
    register_local_delivery,
)
from qc_tool.frontend.dashboard.views.api_access.deliveries.registration.s3 import (
    register_s3_delivery,
)


__all__ = ("register_local_delivery", "register_s3_delivery")
