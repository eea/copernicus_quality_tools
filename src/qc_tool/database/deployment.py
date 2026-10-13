"""Initialize an empty current-model database, or inspect an existing one."""

from contextlib import contextmanager
from pathlib import Path
import re

from django.apps import apps
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.db import models

from qc_tool.database.policy import DatabasePolicyError, load_policy
from qc_tool.database.predicates import named_sqlite_check, predicate_signature

# Preserve the existing application-wide advisory-lock identity.
SCHEMA_LOCK = (1363366991, 1)

@contextmanager
def schema_lock(connection, *, lock_timeout_ms, statement_timeout_ms):
    """Serialize explicit initialization and restore session timeout settings."""
    if connection.vendor != "postgresql":
        yield
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", SCHEMA_LOCK)
        if not cursor.fetchone()[0]:
            raise CommandError("Another QC Tool database initialization job is running.")
        previous = {}
        try:
            for setting, value in (("lock_timeout", lock_timeout_ms),
                                   ("statement_timeout", statement_timeout_ms)):
                cursor.execute("SELECT current_setting(%s)", [setting])
                previous[setting] = cursor.fetchone()[0]
                cursor.execute("SELECT set_config(%s, %s, false)", [setting, f"{value}ms"])
            yield
        finally:
            if connection.connection is not None and connection.is_usable():
                try:
                    for setting, value in previous.items():
                        cursor.execute("SELECT set_config(%s, %s, false)", [setting, value])
                finally:
                    cursor.execute("SELECT pg_advisory_unlock(%s, %s)", SCHEMA_LOCK)

def _native_type(value, vendor):
    value = re.sub(r"\s+", "", value.casefold())
    if vendor == "postgresql":
        for old, new in (("charactervarying", "varchar"), ("int8", "bigint"),
                         ("int4", "integer"), ("int2", "smallint"),
                         ("bool", "boolean"), ("float8", "doubleprecision"),
                         ("decimal", "numeric")):
            if value == old or value.startswith(old + "("):
                value = new + value[len(old):]
                break
    return value

def _index_signature(sql):
    """Normalize current simple/LOWER indexes across SQLite and PostgreSQL."""
    sql = "".join(part if position % 2 else part.casefold().replace('"', '')
                  for position, part in enumerate(re.split(r"('(?:''|[^'])*')", sql)))
    sql = re.sub(r"::(?:text|character\s+varying|varchar)(?:\(\d+\))?", "", sql)
    sql = re.sub(r"\busing\s+btree\b", "", sql)
    match = re.search(r"\bon\s+(?:\w+\.)?\w+\s+(.*)", sql)
    if not match:
        return None
    expression, separator, condition = match.group(1).partition(" where ")
    expression = re.sub(r"[\s()]", "", expression)
    return expression, predicate_signature(condition) if separator else None


def _index_matches(definition, expected):
    if not definition or expected is None:
        return False
    try:
        expected_signature = _index_signature(str(expected))
        return expected_signature is not None and _index_signature(definition) == expected_signature
    except ValueError:
        return False

class SchemaInitializer:
    """Existing schemas are inspected only; only an empty target is initialized."""

    def __init__(self, connection):
        self.connection = connection
        self.models = [model for model in apps.get_models(include_auto_created=True)
                       if model._meta.can_migrate(connection)]

    def _missing_sqlite_file(self):
        name = str(self.connection.settings_dict["NAME"])
        return (self.connection.vendor == "sqlite" and name != ":memory:"
                and not name.startswith("file:") and not Path(name).exists())

    def _column_types(self, cursor, table, columns):
        if self.connection.vendor == "postgresql":
            cursor.execute(
                "SELECT attname, format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = %s::regclass AND attnum > 0 AND NOT attisdropped", [table],
            )
            return dict(cursor.fetchall())
        return {column.name: str(column.type_code) for column in columns}

    def _index_sql(self, cursor, table, name):
        if self.connection.vendor == "postgresql":
            cursor.execute(
                "SELECT pg_get_indexdef(i.indexrelid) FROM pg_index i "
                "JOIN pg_class c ON c.oid=i.indexrelid "
                "WHERE i.indrelid=%s::regclass AND c.relname=%s", [table, name],
            )
        else:
            cursor.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name=%s", [name])
        row = cursor.fetchone()
        return row[0] if row else None

    def _table_sql(self, cursor, table):
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=%s", [table])
        row = cursor.fetchone()
        return row[0] if row else ""

    def _check_sql(self, cursor, table, name):
        if self.connection.vendor == "postgresql":
            cursor.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                           "WHERE conrelid=%s::regclass AND conname=%s AND contype='c'", [table, name])
            row = cursor.fetchone()
            return row[0] if row else None
        return named_sqlite_check(self._table_sql(cursor, table), name)

    def _automatic_primary_key(self, cursor, model):
        field = model._meta.pk
        if not isinstance(field, (models.AutoField, models.BigAutoField, models.SmallAutoField)):
            return True
        table = model._meta.db_table
        if self.connection.vendor == "postgresql":
            cursor.execute("SELECT a.attidentity, pg_get_expr(d.adbin,d.adrelid), "
                           "pg_get_serial_sequence(%s,%s) FROM pg_attribute a "
                           "LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum "
                           "WHERE a.attrelid=%s::regclass AND a.attname=%s",
                           [table, field.column, table, field.column])
            row = cursor.fetchone()
            return bool(row and row[2] and (row[0] == "d" or
                        (not row[0] and row[1] and "nextval(" in row[1])))
        return bool(re.search(r"\bAUTOINCREMENT\b", self._table_sql(cursor, table), re.I))

    def _objects(self, cursor):
        if self.connection.vendor != "postgresql":
            tables = {table.name: table.type for table in self.connection.introspection.get_table_list(cursor)}
            return tables, []
        cursor.execute("SELECT current_schema()")
        schema = cursor.fetchone()[0]
        namespace_filter = ("n.nspname NOT IN ('pg_catalog','information_schema') "
                            "AND n.nspname NOT LIKE 'pg_toast%' AND n.nspname NOT LIKE 'pg_temp_%'")
        cursor.execute("SELECT n.nspname,c.relname,c.relkind FROM pg_class c "
                       "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE " + namespace_filter +
                       " AND c.relkind IN ('r','p','v','m','f','c')")
        tables = {(name if namespace == schema else f"{namespace}.{name}"):
                  ("t" if kind in {"r", "p"} else "v") for namespace, name, kind in cursor.fetchall()}
        expected = {(schema, model._meta.db_table) for model in self.models}
        cursor.execute("SELECT n.nspname,s.relname,tn.nspname,t.relname FROM pg_class s "
                       "JOIN pg_namespace n ON n.oid=s.relnamespace "
                       "LEFT JOIN pg_depend d ON d.classid='pg_class'::regclass AND d.objid=s.oid "
                       "AND d.deptype IN ('a','i') LEFT JOIN pg_class t ON t.oid=d.refobjid "
                       "LEFT JOIN pg_namespace tn ON tn.oid=t.relnamespace "
                       "WHERE s.relkind='S' AND " + namespace_filter)
        problems = [f"unexpected sequence {namespace}.{name}" for namespace, name, owner_schema, owner in cursor.fetchall()
                    if (owner_schema, owner) not in expected]
        # A relation-free database with a foreign function/type is not an empty
        # initialization target. Do not silently add application tables to it.
        if not tables:
            cursor.execute("SELECT n.nspname,p.proname FROM pg_proc p "
                           "JOIN pg_namespace n ON n.oid=p.pronamespace WHERE " + namespace_filter)
            problems += [f"unexpected function {namespace}.{name}" for namespace, name in cursor.fetchall()]
            cursor.execute("SELECT n.nspname,t.typname FROM pg_type t "
                           "JOIN pg_namespace n ON n.oid=t.typnamespace WHERE " + namespace_filter +
                           " AND t.typtype IN ('d','e','r','m')")
            problems += [f"unexpected type {namespace}.{name}" for namespace, name in cursor.fetchall()]
        return tables, problems

    def _model_problems(self, cursor, model):
        connection = self.connection
        table = model._meta.db_table
        description = connection.introspection.get_table_description(cursor, table)
        columns = {column.name: column for column in description}
        fields = {field.column: field for field in model._meta.local_fields}
        problems = []
        if columns.keys() != fields.keys():
            problems.append(f"columns differ in {table}")
        types = self._column_types(cursor, table, description)
        for name in columns.keys() & fields.keys():
            field = fields[name]
            if _native_type(types[name], connection.vendor) != _native_type(field.db_type(connection), connection.vendor):
                problems.append(f"column type differs in {table}.{name}")
            if bool(columns[name].null_ok) != bool(field.null):
                problems.append(f"column nullability differs in {table}.{name}")
            if (connection.vendor == "sqlite" and isinstance(field, models.JSONField)
                    and not getattr(columns[name], "has_json_constraint", False)):
                problems.append(f"JSON validation differs in {table}.{name}")
        constraints = connection.introspection.get_constraints(cursor, table)
        if connection.vendor == "postgresql":
            cursor.execute("SELECT conname FROM pg_constraint WHERE conrelid=%s::regclass "
                           "AND NOT convalidated", [table])
            problems += [f"unvalidated constraint {name}" for (name,) in cursor.fetchall()]
            cursor.execute("SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid "
                           "WHERE i.indrelid=%s::regclass AND (NOT i.indisvalid OR NOT i.indisready)", [table])
            problems += [f"invalid or unready index {name}" for (name,) in cursor.fetchall()]
        values = list(constraints.values())
        if not any(item.get("primary_key") and item.get("columns") == [model._meta.pk.column] for item in values):
            problems.append(f"primary key differs in {table}")
        if not self._automatic_primary_key(cursor, model):
            problems.append(f"automatic primary key generation differs in {table}")
        unique_columns = [[field.column] for field in fields.values() if field.unique and not field.primary_key]
        unique_columns += [[model._meta.get_field(name).column for name in names]
                           for names in model._meta.unique_together]
        for names in unique_columns:
            candidates = [(name, item) for name, item in constraints.items()
                          if item.get("unique") and item.get("columns") == names]
            unconditional = False
            for name, item in candidates:
                definition = self._index_sql(cursor, table, name) if item.get("index") else None
                if not item.get("index") or (definition and not re.search(r"\bWHERE\b", definition, re.I)):
                    unconditional = True
            if not unconditional:
                problems.append(f"unique key differs in {table} ({', '.join(names)})")
        for field in fields.values():
            if field.is_relation and getattr(field, "db_constraint", False):
                target = (field.remote_field.model._meta.db_table, field.target_field.column)
                if not any(item.get("columns") == [field.column] and item.get("foreign_key") == target for item in values):
                    problems.append(f"foreign key differs in {table}.{field.column}")
        editor = connection.schema_editor()
        for rule in model._meta.constraints:
            actual = constraints.get(rule.name)
            kind = "check" if isinstance(rule, models.CheckConstraint) else "unique"
            if not actual or not actual.get(kind):
                problems.append(f"missing or different constraint {rule.name}")
                continue
            if isinstance(rule, models.CheckConstraint):
                definition = self._check_sql(cursor, table, rule.name)
                try:
                    expected_predicate = predicate_signature(rule._get_check_sql(model, editor))
                    if not definition or predicate_signature(definition) != expected_predicate:
                        problems.append(f"check expression differs for {rule.name}")
                except ValueError:
                    problems.append(f"cannot verify check expression for {rule.name}")
            names = [model._meta.get_field(name).column for name in getattr(rule, "fields", ())]
            if names and actual.get("columns") != names:
                problems.append(f"constraint columns differ for {rule.name}")
            if getattr(rule, "condition", None) is not None and isinstance(rule, models.UniqueConstraint):
                expected = rule.create_sql(model, editor)
                definition = self._index_sql(cursor, table, rule.name)
                if not _index_matches(definition, expected):
                    problems.append(f"conditional unique key differs for {rule.name}")
        for index in model._meta.indexes:
            actual = constraints.get(index.name)
            if not actual or not actual.get("index") or actual.get("unique"):
                problems.append(f"missing or different index {index.name}")
                continue
            if index.fields:
                names = [model._meta.get_field(name.lstrip("-")).column for name in index.fields]
                orders = ["DESC" if name.startswith("-") else "ASC" for name in index.fields]
                if actual.get("columns") != names or (actual.get("orders") and actual["orders"] != orders):
                    problems.append(f"index columns/order differ for {index.name}")
            if index.expressions or index.condition is not None:
                expected = index.create_sql(model, editor)
                definition = self._index_sql(cursor, table, index.name)
                if not _index_matches(definition, expected):
                    problems.append(f"index expression/condition differs for {index.name}")
        return problems

    def inspect(self):
        if self._missing_sqlite_file():
            return {"state": "empty", "problems": [], "table_count": 0}
        with self.connection.cursor() as cursor:
            tables, problems = self._objects(cursor)
            if not tables and not problems:
                return {"state": "empty", "problems": [], "table_count": 0}
            expected = {model._meta.db_table for model in self.models}
            problems += [f"missing table {name}" for name in sorted(expected - tables.keys())]
            problems += [f"unexpected table/view {name}" for name in sorted(tables.keys() - expected)]
            for model in self.models:
                name = model._meta.db_table
                if name not in tables:
                    continue
                if tables[name] != "t":
                    problems.append(f"expected a table for {name}")
                    continue
                problems.extend(self._model_problems(cursor, model))
        return {"state": "incompatible" if problems else "ready", "problems": problems,
                "table_count": len(tables)}

    def check(self):
        report = self.inspect()
        if report["state"] != "ready":
            detail = "; ".join(report["problems"]) if report["problems"] else "database is empty"
            raise CommandError("Current model schema is not ready: " + detail +
                               ". Inspection made no changes.")
        return report

    def apply(self, *, stdout, lock_timeout_ms, statement_timeout_ms):
        with schema_lock(self.connection, lock_timeout_ms=lock_timeout_ms,
                         statement_timeout_ms=statement_timeout_ms):
            report = self.inspect()
            if report["state"] != "empty":
                self.check()
                stdout.write("Current model schema already exists; schema and data unchanged.")
                return
            # Native syncdb creates managed models and auth permissions. All
            # migration modules are disabled, so no schema history is maintained.
            call_command("migrate", database=self.connection.alias, run_syncdb=True,
                         interactive=False, stdout=stdout)
            self.check()
            stdout.write("Initialized the empty database from current models.")

def manage_database(action, *, database, stdout, lock_timeout_ms, statement_timeout_ms):
    try:
        load_policy()
    except DatabasePolicyError as error:
        raise CommandError(str(error)) from error
    initializer = SchemaInitializer(connections[database])
    if action == "apply":
        initializer.apply(stdout=stdout, lock_timeout_ms=lock_timeout_ms,
                          statement_timeout_ms=statement_timeout_ms)
    elif action == "check":
        initializer.check()
    else:
        report = initializer.inspect()
        if report["state"] == "incompatible":
            initializer.check()
        stdout.write("Empty database: explicit apply will initialize current models." if report["state"] == "empty"
                     else "Current model schema is ready; apply would leave schema and data unchanged.")
