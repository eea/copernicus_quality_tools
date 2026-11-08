"""Inventory and pin retained business files without moving their paths."""

from qc_tool.database.transfers import recovery_files, service as transfers
from qc_tool.database.transfers.components import COMPONENT_LABELS, FILE_COMPONENTS
from qc_tool.database.transfers.contracts import digest
from qc_tool.database.transfers.errors import TransferError
from qc_tool.database.transfers.storage_pins import pin_existing_files


def snapshot():
    inventory, entries, content_hash, byte_count = recovery_files.snapshot(limits=transfers._limits())
    fingerprint = digest({"content": content_hash, "roots": recovery_files.storage_identity()})
    return inventory, entries, fingerprint, byte_count


def inventory():
    inventory, entries, fingerprint, byte_count = snapshot()
    summary = inventory.storage["recovery_files"]["component_summary"]
    areas = [{"key": key, "label": COMPONENT_LABELS[key], "status": summary[key]["status"],
              "files_count": summary[key]["files"],
              "byte_count": sum(entry["size"] for entry in entries
                                if recovery_files.component_for(entry["root"], entry["key"]) == key)}
             for key in FILE_COMPONENTS]
    return {"fingerprint": fingerprint,
            "files_count": len(entries), "byte_count": byte_count,
            "areas": areas, "warnings": list(inventory.warnings)}


def pin_original_files(operation):
    """Verify this deployment's physical roots and pin their original bytes."""
    inventory, entries, fingerprint, _byte_count = snapshot()
    if fingerprint != operation["upgrade"]["storage_hash"]:
        raise TransferError("Retained files changed before candidate migration. Preserve both copies and inspect storage.")
    pin_existing_files(operation, inventory.sources, entries)
    operation["result"].update(include_files=True,
        storage={"files_count": len(entries), "mode": "retained_original_paths"})
