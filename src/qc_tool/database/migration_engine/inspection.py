"""Recognize supported source schemas without creating or repairing history."""

from django.core.management.base import CommandError
from django.db.migrations.recorder import MigrationRecorder

from qc_tool.database.policy import BASELINE_TARGETS, load_policy
from .fingerprints import digest, schema_fingerprint
from .history import GRAPH_ERRORS, history_status, load_graph


def _baseline_models(connection):
    loader = load_graph(connection)
    targets = list(BASELINE_TARGETS.items())
    for key in targets:
        if key not in loader.graph.nodes:
            raise CommandError("The reviewed v3.0.0 adoption graph is not installed.")
    return loader.project_state(targets).apps.get_models(include_auto_created=True)


def inspect_source(connection):
    """Recognize only the exact supported history-free predecessor contract."""
    from qc_tool.database.deployment import SchemaInitializer

    policy = load_policy()
    report = SchemaInitializer(connection, models=_baseline_models(connection), allow_history=False,
                               require_history=False, strict=True).inspect()
    return {**report, "source_release": policy["adoption"]["source_release"],
            "source_fingerprint": schema_fingerprint(connection) if report["state"] != "empty" else None}


def migration_status(connection):
    """Return a JSON-safe, read-only migration review for this physical target."""
    from qc_tool.database.deployment import SchemaInitializer

    policy = load_policy()
    initial = SchemaInitializer(connection, require_history=False).inspect()
    history = history_status(connection)
    result = {**history, "release": policy["release"], "source_release": None,
              "source_fingerprint": None, "state": "incompatible"}
    if history["problems"]:
        # Conflicting/invalid installed history must also block a legacy source;
        # its lack of a recorder is never permission to ignore graph errors.
        result["source_fingerprint"] = schema_fingerprint(connection) if initial["state"] != "empty" else None
    elif initial["state"] == "empty":
        result["state"] = "empty"
    elif not MigrationRecorder(connection).has_table():
        source = inspect_source(connection)
        result.update(state="legacy" if source["state"] == "ready" else "incompatible",
                      source_release=source["source_release"], source_fingerprint=source["source_fingerprint"],
                      problems=source["problems"])
    elif not history["problems"]:
        loader = load_graph(connection)
        applied = [tuple((item["app"], item["name"])) for item in history["applied"]]
        try:
            historical = loader.project_state(applied).apps.get_models(include_auto_created=True)
            report = SchemaInitializer(connection, models=historical, require_history=False, strict=True).inspect()
        except GRAPH_ERRORS as error:
            result["problems"] = [f"Installed Django migration state is invalid ({type(error).__name__}): {error}"]
        else:
            result["problems"] = report["problems"]
            result["state"] = ("pending" if history["pending"] else "ready") if report["state"] == "ready" else "incompatible"
            if result["state"] == "ready" and initial["state"] != "ready":
                # Complete historical state is insufficient if this image changed
                # current models without shipping the corresponding native graph.
                # Pending historical sources legitimately have the old shape.
                result.update(state="incompatible", problems=initial["problems"])
        result["source_fingerprint"] = schema_fingerprint(connection)
    result["plan_hash"] = digest(result)
    return result
