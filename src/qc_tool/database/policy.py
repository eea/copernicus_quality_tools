"""Shared database release policy, independent of Django and database access."""

import json
from pathlib import Path
import re


SOURCE_DIRECTORY = "src/qc_tool"
DATABASE_DIRECTORY = f"{SOURCE_DIRECTORY}/database"
MIGRATIONS_DIRECTORY = f"{DATABASE_DIRECTORY}/migrations"
POLICY_PATH = f"{DATABASE_DIRECTORY}/policy.json"

# Django app labels stay stable; only their migration source modules move.
# Add future app mappings here so their schema remains in this same package.
MIGRATION_MODULES = {
    "accounts": "qc_tool.database.migrations.accounts",
    "dashboard": "qc_tool.database.migrations.dashboard",
}

# Draft schema creation must include auth/contenttypes before resolving model
# relations. Disable their history too; a released target always starts fresh
# with the framework's normal migration graph enabled.
FRAMEWORK_APPS = ("admin", "auth", "contenttypes", "sessions")


def migration_modules(policy=None):
    policy = load_policy() if policy is None else policy
    if policy["phase"] == "draft":
        return dict.fromkeys((*FRAMEWORK_APPS, *MIGRATION_MODULES))
    return dict(MIGRATION_MODULES)


class DatabasePolicyError(Exception):
    """The database release policy or proposed history violates its contract."""


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DatabasePolicyError(f"Duplicate database policy key: {key}.")
        result[key] = value
    return result


def parse_policy(document):
    """Validate a JSON policy without opening a database."""
    try:
        policy = json.loads(document, object_pairs_hook=_unique_keys)
    except (TypeError, ValueError, UnicodeDecodeError) as error:
        raise DatabasePolicyError("Database policy must contain valid JSON.") from error
    if not isinstance(policy, dict) or set(policy) != {"phase", "baselines"}:
        raise DatabasePolicyError("Database policy requires only phase and baselines.")
    if policy["phase"] not in ("draft", "released"):
        raise DatabasePolicyError("Database policy phase must be draft or released.")
    baselines = policy["baselines"]
    if not isinstance(baselines, dict):
        raise DatabasePolicyError("Database baselines must be a mapping.")
    if policy["phase"] == "draft" and baselines:
        raise DatabasePolicyError("Draft schema development has no migration baselines.")
    if policy["phase"] == "released" and not baselines:
        raise DatabasePolicyError(
            "Released policy requires the first release's baseline identities."
        )
    for app, name in baselines.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]*", app):
            raise DatabasePolicyError(f"Invalid baseline app label: {app}.")
        if not isinstance(name, str) or not re.fullmatch(r"0001_[a-z0-9_]+", name):
            raise DatabasePolicyError(f"Invalid baseline migration name for {app}.")
    return policy


def baseline_paths(policy):
    """Return repository-relative migration paths from an already valid policy."""
    return tuple(
        f"{MIGRATIONS_DIRECTORY}/{app}/{name}.py"
        for app, name in sorted(policy["baselines"].items())
    )


def load_policy(repository=None):
    """Read the packaged policy, or a comparison checkout for the Git gate."""
    policy_file = (
        Path(__file__).with_name("policy.json")
        if repository is None
        else Path(repository) / POLICY_PATH
    )
    if not policy_file.is_file() or policy_file.is_symlink():
        raise DatabasePolicyError(
            f"The shared database policy must be a regular file at {POLICY_PATH}."
        )
    try:
        document = policy_file.read_bytes()
    except OSError as error:
        raise DatabasePolicyError(f"Cannot read the shared policy at {POLICY_PATH}.") from error
    return parse_policy(document)
