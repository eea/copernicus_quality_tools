"""Retained native backup requirements shared by review and inventory."""

import os

from qc_tool.database.transfers import store
from qc_tool.database.transfers.archive import open_regular, _hash
from qc_tool.database.transfers.components import FILE_COMPONENTS
from qc_tool.database.transfers.errors import TransferError


def full_storage_coverage(selection):
    components = selection.get("components")
    return bool(selection.get("include_files") and
                (components is None or set(FILE_COMPONENTS) <= set(components)))


def package_identity(operation):
    """Hash the retained regular package without following replacement links."""
    with open_regular(store.package_path(operation["id"])) as handle:
        return _hash(handle, os.fstat(handle.fileno()).st_size)


def reviewed_backup(operation_id):
    operation = store.read_operation(operation_id)
    if (operation.get("kind") != "export" or operation.get("profile") != "database"
            or operation.get("status") != "completed" or operation.get("package_release_requested_at")):
        raise TransferError("Choose a retained, completed native PostgreSQL backup.")
    if not full_storage_coverage(operation.get("selection", {})):
        raise TransferError("Create a backup including specifications, boundaries, deliveries, artifacts and publications before upgrading.")
    checksum, size = package_identity(operation)
    if checksum != operation.get("package_sha256") or size != operation.get("package_bytes"):
        raise TransferError("The selected backup changed. Preserve it and create a new verified backup.")
    return operation
