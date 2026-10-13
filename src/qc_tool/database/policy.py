"""The v3.0.0 database is initialized from current models, without history."""

import json
from pathlib import Path

MODELS_ONLY_APPS = ("admin", "auth", "contenttypes", "sessions", "accounts", "dashboard")
MODELS_ONLY_POLICY = {"phase": "draft", "baselines": {}}

class DatabasePolicyError(Exception):
    """The packaged models-only configuration is missing or invalid."""

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
    if policy != MODELS_ONLY_POLICY:
        raise DatabasePolicyError("v3.0.0 requires the models-only configuration with no baselines.")
    return policy

def load_policy(repository=None):
    path = (Path(__file__).with_name("policy.json") if repository is None
            else Path(repository) / "src/qc_tool/database/policy.json")
    if path.is_symlink() or not path.is_file():
        raise DatabasePolicyError("The models-only database configuration must be a regular file.")
    try:
        return parse_policy(path.read_bytes())
    except OSError as error:
        raise DatabasePolicyError("Cannot read the models-only database configuration.") from error

def migration_modules():
    """Disable Django's migration modules; no application history is maintained."""
    load_policy()
    return dict.fromkeys(MODELS_ONLY_APPS)
