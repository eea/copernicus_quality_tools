"""Read-only whole-application readiness for current and historical model states."""

from pathlib import Path
from django.apps import apps
from django.core.management.base import CommandError
from . import catalog
from .models import problems as model_problems
from .strict.objects import problems as object_problems


class SchemaInspector:
    """Read required objects and history without repairing or initializing them."""

    def __init__(self, connection, *, models=None, allow_history=True, require_history=True, strict=False):
        self.connection = connection
        self.models = [model for model in (models if models is not None else apps.get_models(include_auto_created=True))
                       if model._meta.can_migrate(connection)]
        self.allow_history = allow_history
        self.require_history = require_history
        self.strict = strict

    def _missing_sqlite_file(self):
        name = str(self.connection.settings_dict["NAME"])
        return (self.connection.vendor == "sqlite" and name != ":memory:"
                and not name.startswith("file:") and not Path(name).exists())

    def inspect(self):
        if self._missing_sqlite_file():
            return {"state": "empty", "problems": [], "table_count": 0}
        with self.connection.cursor() as cursor:
            tables, problems = catalog.objects(self.connection, cursor, self.models, allow_history=self.allow_history)
            if not tables and not problems:
                return {"state": "empty", "problems": [], "table_count": 0}
            expected = {model._meta.db_table for model in self.models}
            if self.allow_history:
                expected.add("django_migrations")
            # A recorder table is optional only during empty initialization.
            if self.allow_history and "django_migrations" not in tables:
                expected.discard("django_migrations")
            problems += [f"missing table {name}" for name in sorted(expected - tables.keys())]
            problems += [f"unexpected table/view {name}" for name in sorted(tables.keys() - expected)]
            for model in self.models:
                name = model._meta.db_table
                if name not in tables:
                    continue
                if tables[name] != "t":
                    problems.append(f"expected a table for {name}")
                    continue
                problems.extend(model_problems(self.connection, cursor, model, strict_source=self.strict))
            if self.allow_history and "django_migrations" in tables:
                from django.db.migrations.recorder import MigrationRecorder
                problems.extend(model_problems(self.connection, cursor, MigrationRecorder.Migration, strict_source=self.strict))
            if self.strict:
                problems.extend(object_problems(self.connection, cursor))
        if self.require_history and not problems:
            from qc_tool.database.migration_engine import history_status
            history = history_status(self.connection)
            problems.extend(history["problems"])
            if history["pending"]:
                problems.append("Django migrations are pending; use the reviewed candidate upgrade workflow")
        return {"state": "incompatible" if problems else "ready", "problems": problems,
                "table_count": len(tables)}

    def check(self):
        report = self.inspect()
        if report["state"] != "ready":
            detail = "; ".join(report["problems"]) if report["problems"] else "database is empty"
            raise CommandError("Current model schema is not ready: " + detail +
                               ". Inspection made no changes.")
        return report
