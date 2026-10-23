"""Durable maintenance pin: process death must never reopen write admission.

Call pin/unpin only while holding control.lock. Recovery uses the transfer
execution lock and an atomic SQL receipt; elapsed time never releases a pin.
"""

import json
import os
import tempfile
from uuid import UUID

from qc_tool.frontend.dashboard.services.artifacts import open_regular_artifact, ArtifactUnavailable
from .state import MaintenanceError, _directory


def active_operation():
    path = _directory() / "transfer.json"
    try:
        with open_regular_artifact(path.parent, path.name) as handle:
            if os.fstat(handle.fileno()).st_mode & 0o077:
                raise ValueError
            value = json.loads(handle.read(4097))
        if (set(value) != {"operation_id", "kind", "generation"}
                or str(UUID(value["operation_id"])) != value["operation_id"]
                or value["kind"] not in {"export", "import"}
                or type(value["generation"]) is not int or value["generation"] < 0):
            raise ValueError
        return value
    except ArtifactUnavailable:
        # A dangling link or unreadable existing entry is not an absent pin.
        if not path.exists() and not path.is_symlink():
            return None
        raise MaintenanceError("The database transfer pin is unreadable. Operator recovery is required.")
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise MaintenanceError("The database transfer pin is unreadable. Operator recovery is required.") from error


def require_no_operation():
    operation = active_operation()
    if operation:
        raise MaintenanceError("Database transfer {} owns maintenance. Complete or recover it in Data transfer before changing maintenance.".format(operation["operation_id"]))


def pin_operation(operation_id, kind, generation):
    require_no_operation()
    payload = json.dumps({"operation_id": str(UUID(str(operation_id))), "kind": kind,
                          "generation": generation}).encode()
    path = _directory() / "transfer.json"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".transfer-pin-", delete=False) as handle:
            temporary = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        # Fully durable content before exclusive atomic publication. A killed
        # writer can leave a private temp file, never a partially written pin.
        os.link(temporary, path, follow_symlinks=False)
        _sync_directory()
    finally:
        if temporary:
            os.unlink(temporary)


def unpin_operation(operation_id):
    operation = active_operation()
    if not operation or operation["operation_id"] != str(operation_id):
        raise MaintenanceError("Transfer maintenance ownership changed; operator recovery is required.")
    (_directory() / "transfer.json").unlink()
    _sync_directory()


def _sync_directory():
    descriptor = os.open(_directory(), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
