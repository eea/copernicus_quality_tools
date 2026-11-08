"""Reviewed native Django migration policy for the whole application."""

import json
from pathlib import Path

MANAGED_APPS = ("admin", "auth", "contenttypes", "sessions", "accounts", "dashboard", "qc_database")
BASELINE_TARGETS = {
    "admin": "0003_logentry_add_action_flag_choices",
    "auth": "0012_alter_user_first_name_max_length",
    "contenttypes": "0002_remove_content_type_name",
    "sessions": "0001_initial",
    "accounts": "0001_initial",
    "dashboard": "0001_initial",
    "qc_database": "0001_initial",
}
MANAGED_POLICY = {
    "phase": "managed", "release": "3.0.0",
    "adoption": {"source_release": "3.0.0", "targets": BASELINE_TARGETS},
}

class DatabasePolicyError(Exception):
    """The packaged native migration configuration is missing or invalid."""

def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DatabasePolicyError(f"Duplicate database configuration key: {key}.")
        result[key] = value
    return result

def parse_policy(document):
    try:
        policy = json.loads(document, object_pairs_hook=_unique_keys)
    except (TypeError, ValueError, UnicodeDecodeError) as error:
        raise DatabasePolicyError("Database configuration must contain valid JSON.") from error
    if policy != MANAGED_POLICY:
        raise DatabasePolicyError("The database policy must match the reviewed 3.0.0 native migration foundation.")
    return policy

def load_policy(repository=None):
    path = (Path(__file__).with_name("policy.json") if repository is None
            else Path(repository) / "src/qc_tool/database/policy.json")
    if path.is_symlink() or not path.is_file():
        raise DatabasePolicyError("The database policy must be a regular file.")
    try:
        return parse_policy(path.read_bytes())
    except OSError as error:
        raise DatabasePolicyError("Cannot read the database policy.") from error

def migration_modules():
    """Use Django's conventional migration packages, including framework apps."""
    load_policy()
    return {}
