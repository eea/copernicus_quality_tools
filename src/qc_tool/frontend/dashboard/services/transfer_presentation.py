"""Read-only presentation of persisted administrative transfer journals."""

from datetime import datetime

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from qc_tool.database.transfers.recovery_files import EXCLUSIONS, LEGACY_EXCLUSIONS


_BACKUP_EXCLUSIONS = frozenset((*EXCLUSIONS, *LEGACY_EXCLUSIONS,
    "Files outside PostgreSQL and deployment secrets require separate backups."))


def transfer_page_copy(operation, *, native_import=False, needs_destination=False,
                       database_active=False, switch_review=False):
    """Name the user's next step from saved state, without changing that state."""
    status = operation.get("status")
    result = operation.get("result") or {}
    if operation["kind"] == "export":
        if operation.get("recoverable") or status in {"failed", "recovery_required"}:
            return "Backup needs attention", "Review the issue and the available recovery action before continuing."
        if status == "cancelled":
            return "Backup cancelled", "This backup did not finish. Return to Back up & restore to create another."
        if operation.get("payload_released_at"):
            return "Backup ZIP deleted", "The saved ZIP was removed. Its history and checksum remain available."
        if operation.get("package_release_requested_at"):
            return "Backup ZIP deletion pending", "Review this cleanup and finish deleting the saved ZIP if needed."
        if status == "queued":
            return "Backup queued", "Your request is saved. Preparation will continue on the server."
        if status == "running":
            return "Creating your backup", "Follow preparation here or return later to download the finished ZIP."
        if status == "completed" and operation.get("downloadable"):
            return "Backup ready to download", "Download the saved ZIP and keep it in protected storage."
        return "Backup details", "Check this backup's saved status, contents and available actions."
    if not native_import:
        return "Import details", ("Review the records and account choices before adding them to the active database."
                                  if status in {"staged", "planned"} else
                                  "Check this records import and its available next steps.")
    if operation.get("database_deleted_at"):
        return "Restored database removed", "This restored database was removed. Its transfer history is retained."
    if operation.get("database_deletion_requested_at"):
        return "Database removal pending", "Open Manage databases to review and finish this cleanup."
    if operation.get("recoverable") or status in {"failed", "recovery_required"}:
        return "Restore needs attention", "Review the issue and recovery steps before using this database."
    if status == "cancelled":
        return "Restore cancelled", "This restore was cancelled. Return to Back up & restore to choose another backup."
    if status == "queued":
        return "Restore queued", "Your restore request is saved. It will run on the server."
    if status == "running":
        return "Restoring your database", "Follow the restore and verification here. Switching databases comes afterward."
    if switch_review:
        return "Review database switch", "Review the restored database and matching files before choosing to use it."
    if status == "completed" and result.get("verified"):
        if database_active:
            return "Restored database is in use", "Check its records and files, then turn off maintenance when you are ready."
        return "Restored database ready", "The restore is verified. Review a switch to use this database, or keep the current one."
    if status in {"staged", "planned"}:
        return ("Prepare restore destination", "Create a separate empty database for this backup. Your active database is kept.") if needs_destination else (
            "Review database restore", "Check the backup, destination and selected files before starting the restore.")
    return "Restore details", "Check the restore and verification result before deciding which database to use."


def local_datetime(value):
    """Accept journal ISO dates without depending on the application's USE_TZ."""
    if isinstance(value, str):
        try:
            value = parse_datetime(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value)
    return timezone.localtime(value)


def present_transfer(operation):
    """Keep machine journal values intact and add local dates for templates."""
    if not operation:
        return operation
    warnings = (operation.get("result") or {}).get("warnings") or []
    # Native exports historically stored ordinary exclusions alongside warnings.
    # Only classify exact known exclusions; unavailable-file and future warnings
    # must retain their visibility rather than being inferred from their wording.
    exclusions = _BACKUP_EXCLUSIONS if operation.get("kind") == "export" else frozenset()
    return {
        **operation,
        "display_warnings": [item for item in warnings if item not in exclusions],
        "display_exclusions": [item for item in warnings if item in exclusions],
        "display_dates": {
            key: local_datetime(operation.get(key))
            for key in ("created_at", "updated_at", "expires_at", "payload_released_at")
        },
    }


def backup_storage_summary(operations, capacity=None):
    """Separate removable export files from retained import/recovery material.

    Sizes come from the service's no-follow filesystem inventory, rather than
    historical journal sizes: a deleted or unreadable file must not be counted
    as reclaimable storage. Older exports can lack source-database metadata.
    """
    saved_exports = []
    retained_import_bytes = 0
    retained_import_count = 0
    other_package_bytes = 0
    unknown_size_count = 0
    for operation in operations:
        size = operation.get("stored_package_bytes")
        size_known = type(size) is int and size >= 0
        if not size_known:
            unknown_size_count += 1
        removable_export = (operation.get("kind") == "export"
                            and operation.get("status") == "completed"
                            and not operation.get("payload_released_at"))
        if removable_export:
            details = operation.get("source_details")
            source = details.get("source_database") if isinstance(details, dict) else None
            saved_exports.append({
                **present_transfer(operation),
                "backup_source_database": source if isinstance(source, str) and len(source) <= 512 else "",
                "saved_size_known": size_known,
                "saved_file_available": bool(size_known and size > 0),
            })
        elif operation.get("kind") == "import" and size_known and size > 0:
            retained_import_count += 1
            retained_import_bytes += size
        elif size_known:
            other_package_bytes += size
    saved_export_bytes = sum(item["stored_package_bytes"] for item in saved_exports
                             if item["saved_size_known"])
    return {
        "saved_exports": saved_exports,
        "saved_export_count": sum(item["saved_file_available"] for item in saved_exports),
        "saved_export_bytes": saved_export_bytes,
        "reclaimable_bytes": sum(item["stored_package_bytes"] for item in saved_exports
                                 if item["saved_size_known"] and item.get("releasable")),
        "retained_import_count": retained_import_count,
        "retained_import_bytes": retained_import_bytes,
        "other_package_bytes": other_package_bytes,
        "unknown_size_count": unknown_size_count,
        "capacity": capacity,
    }
