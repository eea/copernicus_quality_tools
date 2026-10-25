"""Shared full-backup section identities, independent of Django and storage."""

FILE_COMPONENTS = ("specifications", "boundaries", "deliveries", "artifacts", "publications")
EXPORT_COMPONENT_CHOICES = (
    ("specifications", "Original product specifications"),
    ("boundaries", "Boundary packages"),
    ("deliveries", "Retained delivery ZIPs"),
    ("artifacts", "QC results and artifacts"),
    ("publications", "Published submissions and receipts"),
    ("postgresql_globals", "PostgreSQL roles, role passwords and tablespaces"),
    ("deployment_configuration", "Application configuration and credential files (contains secrets)"),
)
EXPORT_COMPONENTS = tuple(key for key, _label in EXPORT_COMPONENT_CHOICES)
COMPONENT_LABELS = dict(EXPORT_COMPONENT_CHOICES)


def validate(archive):
    """Check explicit section decisions without applying configuration or SQL."""
    from .archive import _json
    from .errors import TransferError

    database = {entry["key"]: entry for entry in archive.entries if entry["root"] == "database"}
    entry = database.get("metadata/selection.json")
    if entry is None:
        return
    if entry["size"] > 1024**2:
        raise TransferError("The backup section selection exceeds its supported size.")
    with archive.open_artifact(entry) as stream:
        document = _json(stream.read(1024**2 + 1))
    if (not isinstance(document, dict)
            or set(document) != {"format", "version", "selected_components", "omitted_components", "components"}
            or document["format"] != "qc-tool-backup-selection"
            or type(document["version"]) is not int or document["version"] != 1):
        raise TransferError("The backup section selection is unsupported.")
    selected, omitted, rows = document["selected_components"], document["omitted_components"], document["components"]
    if (not isinstance(selected, list) or not isinstance(omitted, list)
            or any(not isinstance(key, str) or key not in EXPORT_COMPONENTS for key in [*selected, *omitted])
            or len(set(selected)) != len(selected) or len(set(omitted)) != len(omitted)
            or set(selected) & set(omitted) or set(selected) | set(omitted) != set(EXPORT_COMPONENTS)
            or not isinstance(rows, list) or len(rows) != len(EXPORT_COMPONENTS)):
        raise TransferError("The backup section selection is inconsistent.")
    for key, row in zip(EXPORT_COMPONENTS, rows):
        if (not isinstance(row, dict) or set(row) != {"key", "label", "selected", "status", "files_count", "byte_count"}
                or row["key"] != key or type(row["selected"]) is not bool or row["selected"] != (key in selected)
                or not isinstance(row["label"], str) or len(row["label"]) > 200
                or row["status"] not in {"included", "empty", "partial", "unavailable", "omitted"}
                or (row["status"] == "omitted") != (key in omitted)
                or any(type(row[name]) is not int or row[name] < 0 for name in ("files_count", "byte_count"))):
            raise TransferError("The backup component availability is inconsistent.")
    for component, section in (("postgresql_globals", "metadata/globals.sql"),
                               ("deployment_configuration", "metadata/deployment.json")):
        if (component in selected) != (section in database):
            raise TransferError("The backup section decisions disagree with included metadata.")
    recovery = archive.storage.get("recovery_files") or {}
    if recovery.get("version") == 2 and set(recovery["selected_components"]) != set(selected) & set(FILE_COMPONENTS):
        raise TransferError("The selected backup files disagree with the section decisions.")
