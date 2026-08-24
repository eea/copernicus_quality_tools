"""Authentication helpers for dashboard-specific machine clients."""

from qc_tool.frontend.dashboard.authentication.decorators import (
    worker_token_required,
)


__all__ = ["worker_token_required"]
