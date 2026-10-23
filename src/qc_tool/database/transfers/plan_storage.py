"""Compact replay journals; source records and committed SQL receipts stay full.

The import service rebuilds plans from its verified package before admission and
execution and compares the original full review hash. Journals need replay
decisions and the selected recovery graph, not another copy of every source row.
Compaction never changes the in-memory plan used for insertion/verification.
"""

import re

from .contracts import digest
from .errors import TransferError


_MARKER = "_plan_storage"
_FORMAT = "qc-tool-additive-plan-reference"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_REPLAY_FIELDS = frozenset(("mode", "version", "mappings", "resolutions", "included", "account_choices"))
_KNOWN_FIELDS = _REPLAY_FIELDS | frozenset((
    "profile", "package_digest", "target_fingerprint", "accounts", "blockers", "counts", "exclusions",
    "identity_map", "origins", "actions", "pending", "record_conflicts", "resource_summary", "source_overrides",
))
PUBLIC_RESULT_FIELDS = frozenset((
    "mode", "version", "created_counts", "created_account_keys", "user_mappings",
    "resource_summary", "destination_jobs", "warnings", "updated_counts", "reused_counts",
    "updated_account_keys", "skipped_account_keys", "file_references",
))


def validate_stored_plan(core):
    """Validate our compact reference; old full and unknown plans stay untouched."""
    if not isinstance(core, dict) or _MARKER not in core:
        return core
    marker = core[_MARKER]
    retained = {key: value for key, value in core.items() if key != _MARKER}
    if (set(retained) - _REPLAY_FIELDS or retained.get("mode") != "additive"
            or type(retained.get("version")) is not int or retained["version"] != 1
            or not {"mappings", "resolutions", "included"} <= set(retained)
            or any(not isinstance(retained[key], dict) for key in ("mappings", "resolutions", "included"))
            or any(not isinstance(keys, list) or any(not isinstance(key, str) for key in keys)
                   for keys in retained["included"].values())
            or not isinstance(marker, dict)
            or set(marker) != {"format", "version", "core_sha256", "retained_sha256"}
            or marker["format"] != _FORMAT or type(marker["version"]) is not int or marker["version"] != 1
            or any(not isinstance(marker[key], str) or not _SHA.fullmatch(marker[key])
                   for key in ("core_sha256", "retained_sha256"))
            or marker["retained_sha256"] != digest(retained)):
        raise TransferError("The saved import plan reference is invalid. Preserve its package and review or recover the operation.")
    return core


def compact_plan(core):
    if not isinstance(core, dict):
        return core
    if _MARKER in core:
        return validate_stored_plan(core)
    # Unknown reader/plan revisions must not silently lose private fields.
    if (core.get("mode") != "additive" or type(core.get("version")) is not int or core["version"] != 1
            or set(core) - _KNOWN_FIELDS or not {"pending", "mappings", "resolutions", "included"} <= set(core)):
        return core
    retained = {key: value for key, value in core.items() if key in _REPLAY_FIELDS}
    result = {**retained, _MARKER: {"format": _FORMAT, "version": 1,
                                 "core_sha256": digest(core), "retained_sha256": digest(retained)}}
    return validate_stored_plan(result)


def verify_rebuilt_plan(stored, rebuilt):
    """Optional direct verification; service also checks the full review hash."""
    validate_stored_plan(stored)
    if isinstance(stored, dict) and _MARKER in stored:
        matches = compact_plan(rebuilt) == stored
    else:
        matches = stored == rebuilt
    if not matches:
        raise TransferError("The reviewed import plan changed. Review the package and destination again before importing.")
    return rebuilt


def public_result(result):
    """Return the existing public summary; SQL receipts retain all audit data."""
    if (not isinstance(result, dict) or result.get("mode") not in {"additive", "accounts"}
            or type(result.get("version")) is not int or result["version"] != 1):
        return result
    return {key: value for key, value in result.items() if key in PUBLIC_RESULT_FIELDS}


compact_result = public_result


def compact_operation(operation):
    persisted = dict(operation)
    if "core_plan" in persisted:
        persisted["core_plan"] = compact_plan(persisted["core_plan"])
    if operation.get("kind") == "import":
        persisted["result"] = compact_result(persisted.get("result"))
    return persisted
