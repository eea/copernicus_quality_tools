"""One quiescent barrier for administrative transfers and storage changes."""

from contextlib import contextmanager

from .operations import active_operation, require_no_operation
from .state import MaintenanceBusy, MaintenanceError, file_lock, read_status


@contextmanager
def ready_barrier(generation=None, *, owner=None):
    """Hold control and drained activity until a synchronous action finishes.

    This does not grant administrator authority or classify an HTTP endpoint.
    Callers must authorize and validate their own exact reviewed operation.
    """
    with file_lock("control", blocking=False) as controlled:
        if not controlled:
            raise MaintenanceBusy("Another maintenance action is in progress. Retry shortly.")
        state = read_status()
        if not state["enabled"] or state["phase"] != "ready":
            raise MaintenanceError("Enable maintenance and wait for readiness before continuing.")
        if generation is not None and (type(generation) is not int or state["generation"] != generation):
            raise MaintenanceError("Maintenance changed. Reload and review this action.")
        operation = active_operation()
        if owner is None:
            require_no_operation()
        elif not operation or operation["operation_id"] != str(owner):
            raise MaintenanceError("This transfer no longer owns maintenance. Operator recovery is required.")
        with file_lock("activity", blocking=False) as drained:
            if not drained:
                raise MaintenanceError("Application activity is still stopping. Check maintenance progress.")
            yield state
