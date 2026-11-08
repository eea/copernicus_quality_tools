"""Check the maintained native migration packages without opening a database."""

import os
from pathlib import Path
import re

from qc_tool.database.policy import DatabasePolicyError, load_policy

MIGRATION_PACKAGES = ("database/migrations", "frontend/accounts/migrations", "frontend/dashboard/migrations")


def check_source(source=None):
    """Keep committed history conventional and reject one-off legacy converters."""
    load_policy()
    source = Path(source) if source is not None else Path(__file__).resolve().parents[2]
    for directory, folders, _files in os.walk(source):
        folders[:] = [name for name in folders if name not in ("backups", "__pycache__")]
        if "migrations" in folders:
            path = Path(directory) / "migrations"
            if path.relative_to(source).as_posix() not in MIGRATION_PACKAGES:
                raise DatabasePolicyError(f"Unowned first-party migration package: {path}")
            for member in path.iterdir():
                if member.name == "__pycache__":
                    continue
                if (member.is_symlink() or not member.is_file()
                        or not (member.name == "__init__.py" or re.fullmatch(r"\d{4}_[a-z0-9_]+\.py", member.name))):
                    raise DatabasePolicyError(f"Unexpected migration-package member: {member}")
    for relative in ("database/legacy", "database/management/commands/import_legacy_dump.py"):
        if (source / relative).exists():
            raise DatabasePolicyError("Manual legacy conversion must stay outside application source.")
    if source == Path(__file__).resolve().parents[2]:
        for relative in MIGRATION_PACKAGES:
            package = source / relative
            if not (package / "__init__.py").is_file() or not (package / "0001_initial.py").is_file():
                raise DatabasePolicyError(f"The reviewed initial Django history is missing: {package}")


def main():
    try:
        check_source()
    except DatabasePolicyError as error:
        raise SystemExit(str(error)) from error
    print("Native Django history: owned migration packages and no legacy converter.")


if __name__ == "__main__":
    main()
