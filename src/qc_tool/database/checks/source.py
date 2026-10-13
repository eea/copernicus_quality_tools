"""Check the v3 models-only source contract without opening a database."""

import os
from pathlib import Path

from qc_tool.database.policy import DatabasePolicyError, load_policy


def check_source(source=None):
    """Reject first-party migration packages and retained one-off converters."""
    load_policy()
    source = Path(source) if source is not None else Path(__file__).resolve().parents[2]
    for directory, folders, _files in os.walk(source):
        # Local private backups and generated caches are not application source.
        folders[:] = [name for name in folders if name not in ("backups", "__pycache__")]
        if "migrations" in folders:
            raise DatabasePolicyError(
                f"v3.0.0 has no first-party migration package: {Path(directory) / 'migrations'}"
            )
    for relative in (
        "database/legacy",
        "database/management/commands/import_legacy_dump.py",
    ):
        if (source / relative).exists():
            raise DatabasePolicyError("Manual legacy conversion must stay outside application source.")


def main():
    try:
        check_source()
    except DatabasePolicyError as error:
        raise SystemExit(str(error)) from error
    print("Models-only source: no first-party migration packages or legacy converter.")


if __name__ == "__main__":
    main()
