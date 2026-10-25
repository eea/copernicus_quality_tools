"""Small, throttled export progress beside the durable operation journal.

The runner owns these writes. Status GETs only read them; browser connections
and polling do not own, pause or cancel preparation. No paths or secrets enter
this public summary. The execution lock remains the authority for liveness.
"""

from datetime import datetime
import logging
import time

from . import store
from .errors import TransferError


logger = logging.getLogger(__name__)
INTERVAL_SECONDS = 2.0
MAX_PROGRESS_BYTES = 8192
LABELS = {
    "queued": "Waiting for the background export runner",
    "validating": "Checking the reviewed export",
    "scan_files": "Listing the selected files",
    "hash_files": "Checking the selected file contents",
    "inventory_database": "Checking database records in batches",
    "database_dump": "Writing the PostgreSQL backup",
    "readable_schema": "Preparing schema and database metadata",
    "postgresql_globals": "Preparing PostgreSQL roles and tablespaces",
    "copy_files": "Copying selected files into the ZIP",
    "verify_package": "Verifying the prepared ZIP",
    "publishing": "Saving the completed package",
    "completed": "Package ready to download",
    "cancelled": "Export cancelled",
    "recovery_required": "Export needs recovery",
    "released": "Export package released from server storage",
}
COUNTERS = ("processed_bytes", "total_bytes", "processed_items", "total_items")


def _summary(phase, updated_at, **counts):
    return {"phase": phase, "label": LABELS[phase], "updated_at": updated_at,
            **{name: counts.get(name) for name in COUNTERS}}


class Reporter:
    """Coalesce frequent chunk callbacks; phase transitions persist immediately."""

    def __init__(self, operation_id, *, clock=time.monotonic):
        self.operation_id = operation_id
        self.clock = clock
        self.last_write = None
        self.current = None
        self.write_failed = False

    def __call__(self, phase, *, processed_bytes=None, total_bytes=None, processed_items=None, total_items=None):
        if phase not in LABELS:
            raise ValueError("Choose a known export progress phase.")
        values = dict(zip(COUNTERS, (processed_bytes, total_bytes, processed_items, total_items)))
        if any(value is not None and (type(value) is not int or value < 0) for value in values.values()):
            raise ValueError("Export progress counters must be nonnegative integers.")
        changed = self.current is None or self.current["phase"] != phase
        if not changed:
            values = {name: self.current[name] if value is None else value for name, value in values.items()}
        self.current = _summary(phase, store.now(), **values)
        observed = self.clock()
        if not changed and self.last_write is not None and observed - self.last_write < INTERVAL_SECONDS:
            return
        self.last_write = observed
        try:
            store.write_json(store.operation_dir(self.operation_id) / "progress.json",
                             {"version": 1, "operation_id": self.operation_id, **self.current})
            self.write_failed = False
        except (TransferError, OSError):
            # Progress is advisory. Never interrupt a valid archive or replace
            # its authoritative journal merely because this small hint failed.
            if not self.write_failed:
                logger.warning("Export progress could not be saved for operation %s.", self.operation_id)
            self.write_failed = True


def read(operation):
    if operation.get("kind") != "export":
        return None
    phase = {"staged": "queued", "queued": "queued", "running": "validating",
             "completed": "completed", "cancelled": "cancelled",
             "failed": "recovery_required", "recovery_required": "recovery_required"}.get(operation["status"], "validating")
    fallback = _summary(phase, operation["updated_at"])
    if operation.get("package_release_requested_at"):
        return _summary("released", operation.get("payload_released_at") or operation["updated_at"])
    if operation["status"] == "completed":
        size = operation.get("package_bytes")
        return _summary("completed", operation["updated_at"], processed_bytes=size, total_bytes=size)
    if operation["status"] not in {"queued", "running"}:
        return fallback
    try:
        value = store.read_json(store.operation_dir(operation["id"]) / "progress.json", limit=MAX_PROGRESS_BYTES)
        if (not isinstance(value, dict) or set(value) != {"version", "operation_id", "phase", "label", "updated_at", *COUNTERS}
                or type(value["version"]) is not int or value["version"] != 1 or value["operation_id"] != operation["id"]
                or not isinstance(value["phase"], str) or value["phase"] not in LABELS
                or value["label"] != LABELS[value["phase"]]
                or any(value[name] is not None and (type(value[name]) is not int or value[name] < 0) for name in COUNTERS)
                or datetime.fromisoformat(value["updated_at"]).utcoffset() is None):
            return fallback
        return {key: value[key] for key in ("phase", "label", *COUNTERS, "updated_at")}
    except (TransferError, OSError, ValueError, TypeError):
        return fallback
