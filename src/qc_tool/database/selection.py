"""Private database selection for one configured PostgreSQL deployment.

The pointer selects a database, never a server, credential, schema conversion
or destructive operation. Callers serialize writes with the transfer execution
lease and the ready maintenance guard before changing it.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
from threading import RLock

from django.conf import settings
from django.db import connections

from qc_tool.database.transfers import store
from qc_tool.database.transfers.errors import TransferError


_database = ContextVar("qc_database_selection", default=None)
_alias_lock = RLock()
POSTGRESQL_ENGINES = {
    "django.db.backends.postgresql",
    "qc_tool.database.backends.postgresql",
}


class DatabaseSelectionError(TransferError):
    pass


def configured_connection():
    return getattr(settings, "QC_TOOL_CONFIGURED_DATABASE", settings.DATABASES["default"])


def _identity():
    config = configured_connection()
    return {key: str(config.get(source, "")) for key, source in (
        ("name", "NAME"), ("host", "HOST"), ("port", "PORT"), ("user", "USER"),
    )}


def _valid_name(name):
    try:
        return (
            isinstance(name, str) and bool(name) and "\x00" not in name
            and len(name.encode("utf-8")) <= 63
        )
    except UnicodeError:
        return False


def _default_state():
    identity = _identity()
    return {
        "version": 1, "configured": identity, "active": identity["name"],
        "previous": None, "revision": 0, "operation_id": None, "changed_at": None,
    }


def _validate(state):
    if (not isinstance(state, dict) or type(state.get("version")) is not int or state["version"] != 1
            or state.get("configured") != _identity()
            or type(state.get("revision")) is not int or state["revision"] < 0
            or not _valid_name(state.get("active"))
            or (state.get("previous") is not None and (
                not _valid_name(state["previous"]) or state["previous"] == state["active"]
            ))
            or (state.get("operation_id") is not None
                and not isinstance(state["operation_id"], str))
            or ("maintenance_generation" in state and (
                type(state["maintenance_generation"]) is not int or state["maintenance_generation"] < 0
            ))
            or ("activation" in state and not isinstance(state["activation"], dict))
            or ("actor_name" in state and not isinstance(state["actor_name"], str))):
        raise DatabaseSelectionError("Database selection is invalid or belongs to another deployment. Operator recovery is required.")
    if state["revision"]:
        try:
            if datetime.fromisoformat(state["changed_at"]).utcoffset() is None:
                raise ValueError
        except (KeyError, TypeError, ValueError) as error:
            raise DatabaseSelectionError("Database selection has an invalid timestamp. Operator recovery is required.") from error
    return state


def read_state():
    config = configured_connection()
    if config.get("ENGINE") not in POSTGRESQL_ENGINES:
        return _default_state()
    path = store._directory_path() / "database-selection.json"
    if not path.exists() and not path.is_symlink():
        return _default_state()
    # Validate the private parent as well as the journal's regular-file mode.
    try:
        store.directory()
        return _validate(store.read_json(path, limit=16 * 1024))
    except TransferError as error:
        raise DatabaseSelectionError(str(error)) from error


def write_state(state, expected_revision):
    """Persist a reviewed next revision; callers already own the control locks."""
    if configured_connection().get("ENGINE") not in POSTGRESQL_ENGINES:
        raise DatabaseSelectionError("Database switching requires PostgreSQL.")
    current = read_state()
    if type(expected_revision) is not int or current["revision"] != expected_revision:
        raise DatabaseSelectionError("The active database changed. Reload and review the destination again.")
    value = _validate(deepcopy(state))
    if value["revision"] != expected_revision + 1:
        raise DatabaseSelectionError("Database selection must advance by one revision.")
    try:
        if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 16 * 1024:
            raise ValueError
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise DatabaseSelectionError("Database selection metadata exceeds its supported private journal format.") from error
    store.write_json(store.directory() / "database-selection.json", value)
    return value


def current_database():
    frozen = _database.get()
    if frozen is not None:
        return frozen
    configured = configured_connection()
    connection = connections["default"]
    # Django's test runner replaces NAME before creating a disposable schema.
    # Never follow a deployment pointer into its retained database in that case.
    if (connection.settings_dict.get("NAME") != configured.get("NAME")
            or configured.get("ENGINE") not in POSTGRESQL_ENGINES):
        return connection.settings_dict.get("NAME")
    return read_state()["active"]


@contextmanager
def database_scope(name):
    token = _database.set(name)
    try:
        yield
    finally:
        _database.reset(token)


def alias_for_database(name):
    """Return a pinned same-cluster alias; no credential enters the pointer."""
    config = configured_connection()
    if config.get("ENGINE") not in POSTGRESQL_ENGINES:
        if name == current_database():
            return "default"
        raise DatabaseSelectionError("Database switching requires PostgreSQL.")
    if not _valid_name(name):
        raise DatabaseSelectionError("Choose a valid PostgreSQL database name.")
    source = connections["default"]
    # During tests an origin equal to the disposable default stays on its alias.
    if name == source.settings_dict.get("NAME") and name != config.get("NAME"):
        return "default"
    identity = repr((_identity(), name)).encode("utf-8")
    alias = "qc_database_" + sha256(identity).hexdigest()[:24]
    with _alias_lock:
        if alias not in connections.databases:
            value = deepcopy(source.settings_dict)
            value.update(NAME=name, CONN_MAX_AGE=0)
            options = dict(value.get("OPTIONS", {}))
            options["options"] = (options.get("options", "") + " -c default_transaction_read_only=on").strip()
            value["OPTIONS"] = options
            value["TEST"] = {**value.get("TEST", {}), "MIRROR": None}
            connections.databases[alias] = value
    return alias
