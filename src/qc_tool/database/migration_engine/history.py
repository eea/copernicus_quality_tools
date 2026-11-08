"""Read the installed native migration graph and recorded history."""

import hashlib
import importlib
from pathlib import Path

from django.core.management.base import CommandError
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.exceptions import (
    BadMigrationError, CircularDependencyError, InvalidBasesError, NodeNotFoundError,
)
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder

GRAPH_ERRORS = (BadMigrationError, CircularDependencyError, InvalidBasesError, NodeNotFoundError,
                ImportError, SyntaxError)


def load_graph(connection):
    """Give callers an actionable blocker for a broken installed graph."""
    try:
        return MigrationLoader(connection, ignore_no_migrations=True)
    except GRAPH_ERRORS as error:
        raise CommandError(f"Installed Django migration graph is invalid ({type(error).__name__}): {error}") from error


def graph_fingerprint(loader):
    """Bind a review to installed migration bytes, not only migration names."""
    result = []
    for key, migration in sorted(loader.disk_migrations.items()):
        module = importlib.import_module(migration.__module__)
        path = Path(module.__file__)
        result.append({"app": key[0], "name": key[1], "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return result


def history_status(connection):
    """Read Django's graph/recorder without creating the recorder table."""
    try:
        loader = load_graph(connection)
    except CommandError as error:
        # The recorder read is safe even when installed dependencies cannot be
        # resolved. Never repair history or ask Django to create its table here.
        applied = MigrationRecorder(connection).applied_migrations()
        return {"applied": [{"app": app, "name": name} for app, name in sorted(applied)],
                "pending": [], "targets": [], "graph": [], "problems": [str(error)]}
    applied = set(loader.applied_migrations)
    problems = []
    unknown = applied - set(loader.disk_migrations)
    problems.extend(f"unknown applied Django migration {app}.{name}" for app, name in sorted(unknown))
    if MigrationRecorder(connection).has_table():
        from django.db.models import Count
        duplicates = (MigrationRecorder(connection).migration_qs.values("app", "name")
                      .annotate(count=Count("id")).filter(count__gt=1))
        problems.extend(f"duplicate applied Django migration {item['app']}.{item['name']}" for item in duplicates)
    conflicts = loader.detect_conflicts()
    problems.extend(f"conflicting Django migration leaves for {app}: {', '.join(names)}"
                    for app, names in sorted(conflicts.items()))
    try:
        loader.check_consistent_history(connection)
    except Exception as error:
        # Django's message contains graph identities, never connection secrets.
        from django.db.migrations.exceptions import InconsistentMigrationHistory
        if not isinstance(error, InconsistentMigrationHistory):
            raise
        problems.append(str(error))
    targets = loader.graph.leaf_nodes()
    plan = [] if problems else MigrationExecutor(connection).migration_plan(targets)
    if any(backwards for _migration, backwards in plan):
        problems.append("the installed graph would require a reverse migration")
    return {"applied": [{"app": app, "name": name} for app, name in sorted(applied)],
            "pending": [{"app": migration.app_label, "name": migration.name,
                         "atomic": migration.atomic,
                         "operations": [operation.describe() for operation in migration.operations]}
                        for migration, backwards in plan if not backwards],
            "targets": [{"app": app, "name": name} for app, name in targets],
            "graph": graph_fingerprint(loader), "problems": problems}
