"""Read-only startup admission for a retained maintenance recovery database."""

from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.db import DatabaseError, connections
from django.db.models import Q

from qc_tool.database import selection
from qc_tool.database.policy import DatabasePolicyError, load_policy
from qc_tool.database.transfers.errors import TransferError
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.dashboard.services.maintenance.state import read_status
from qc_tool.frontend.dashboard.services.maintenance.reads import _read_query


def _usable_administrator(alias):
    administrators = get_user_model().objects.using(alias).filter(
        is_active=True, is_staff=True,
    ).filter(Q(is_superuser=True) | Q(groups__name=Role.ADMIN.value)).distinct()
    if not any(user.has_usable_password() for user in administrators):
        raise TransferError("The retained database has no usable active QC Tool administrator.")


def maintenance_upgrade_database():
    """Admit Admin recovery for a supported source in an already ready pause.

    This includes the configured v3.0.0 database before the first selection.
    The source remains history-free and read-only; only a separate restored
    candidate can adopt or migrate. Ordinary readiness still refuses it.
    """
    from qc_tool.database.migration_engine import migration_status

    state, maintenance = selection.read_state(), read_status()
    if not maintenance["enabled"] or maintenance["phase"] != "ready":
        raise TransferError("Database upgrades require maintenance to have reached ready before deploying the new release.")
    # The request/startup default is already pinned to the active selection.
    # Reuse it under a read-only query guard instead of opening an additional
    # alias to a possibly unavailable selected copy during recovery.
    alias = "default"
    try:
        source = connections[alias]
        with selection.database_scope(state["active"]), source.execute_wrapper(_read_query):
            report = migration_status(source)
            if report["state"] not in {"legacy", "pending"}:
                raise TransferError("The active database is not a supported upgrade source. Preserve it and inspect schema/history drift.")
            _usable_administrator(alias)
    except (DatabaseError, CommandError) as error:
        raise TransferError("The upgrade source could not be verified read-only. Preserve it and inspect schema/history and administrator access.") from error
    after = read_status()
    if (selection.read_state() != state or not after["enabled"] or after["phase"] != "ready"
            or after["generation"] != maintenance["generation"]):
        raise TransferError("Database selection or maintenance changed during upgrade admission. Retry the read-only check.")
    return state["active"]


def maintenance_recovery_database():
    """Admit recovery UI only; do not repair or activate either database."""
    try:
        load_policy()
    except DatabasePolicyError as error:
        raise TransferError("The database policy must be valid before maintenance recovery startup.") from error
    # The first managed release must be able to display its recovery controls
    # while the original supported predecessor remains selected. This branch
    # never initializes or records migration history on that source.
    try:
        return maintenance_upgrade_database()
    except TransferError:
        pass
    state = selection.read_state()
    maintenance = read_status()
    evidence = state.get("activation") or {}
    native, files = evidence.get("source_native"), evidence.get("source_files")
    if (not state["revision"] or not state.get("previous")
            or not maintenance["enabled"] or maintenance["phase"] != "ready"
            or state.get("maintenance_generation") != maintenance["generation"]
            or not isinstance(native, dict) or type(native.get("oid")) is not int
            or not native.get("review_hash") or not isinstance(files, dict) or not files.get("fingerprint")):
        raise TransferError("Maintenance recovery needs a verified retained database in the same ready maintenance window.")
    alias = selection.alias_for_database(state["previous"])
    try:
        retained = connections[alias]
        with retained.execute_wrapper(_read_query):
            with retained.cursor() as cursor:
                cursor.execute("SELECT current_database(), oid FROM pg_database WHERE datname=current_database()")
                identity = cursor.fetchone()
            if identity != (state["previous"], native["oid"]):
                raise TransferError("The retained database identity changed. Operator recovery is required.")
            from qc_tool.database.migration_engine import migration_status
            report = migration_status(retained)
            if report["state"] not in {"ready", "legacy", "pending"}:
                raise TransferError("The retained database does not match a supported recovery schema/history. Preserve both copies for inspection.")
            _usable_administrator(alias)
    except (DatabaseError, CommandError) as error:
        raise TransferError("The retained database is unavailable or does not match current models. Operator recovery is required.") from error
    finally:
        if alias != "default":
            connections[alias].close()
    after = read_status()
    if (selection.read_state() != state or not after["enabled"] or after["phase"] != "ready"
            or after["generation"] != maintenance["generation"]):
        raise TransferError("Database selection or maintenance changed during recovery startup. Retry the read-only check.")
    return state["previous"]
