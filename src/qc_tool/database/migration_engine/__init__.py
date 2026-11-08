"""Native migration inspection and isolated candidate execution.

The public API stays independent of the backup and database-selection workflow.
Read-only graph/schema inspection and writable candidate admission have separate
owners; neither entry point selects a database or moves retained files.
"""

from .candidates import adopt_candidate_baseline, apply_candidate
from .fingerprints import schema_fingerprint
from .history import history_status
from .inspection import inspect_source, migration_status

__all__ = [
    "adopt_candidate_baseline", "apply_candidate", "history_status",
    "inspect_source", "migration_status", "schema_fingerprint",
]
