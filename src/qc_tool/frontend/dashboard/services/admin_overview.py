"""Read-only navigation hints for the administration home.

Use the admission decision already made by middleware. Opening the overview
must never poll workers, inspect/repair schemas, or advance an operation.
"""

from qc_tool.frontend.accounts.authorization import access_for_request
from .maintenance.operations import active_operation
from .maintenance.state import MaintenanceError
from .database_navigation import maintenance_operation_url


def overview_context(request):
    if not access_for_request(request).is_administrator:
        return {}
    state = getattr(request, "maintenance_status", {}) or {}
    enabled = getattr(request, "maintenance_active", True)
    phase = state.get("phase", "unavailable")
    if phase not in {"off", "ready", "stopping"} or enabled != (phase != "off"):
        phase = "unavailable"
    transfer_url, transfer_error = "", False
    try:
        operation = active_operation()
        if operation:
            transfer_url = maintenance_operation_url(operation)
    except MaintenanceError:
        transfer_error = True
        phase = "unavailable"
    return {"phase": phase, "transfer_url": transfer_url, "transfer_error": transfer_error,
            "blocker_count": len(state.get("blockers", []))}
