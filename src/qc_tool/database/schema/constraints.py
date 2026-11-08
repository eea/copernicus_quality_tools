"""Check primary/foreign keys, declared constraints and model indexes."""

import re
from django.db import models
from qc_tool.database.predicates import predicate_signature
from .catalog import automatic_primary_key, check_sql, index_sql
from .signatures import index_matches


def key_problems(connection, cursor, model, constraints):
    table = model._meta.db_table
    fields = {field.column: field for field in model._meta.local_fields}
    problems = []
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
    if not automatic_primary_key(connection, cursor, model):
        problems.append(f"automatic primary key generation differs in {table}")
    unique_columns = [[field.column] for field in fields.values() if field.unique and not field.primary_key]
    unique_columns += [[model._meta.get_field(name).column for name in names]
                       for names in model._meta.unique_together]
    for names in unique_columns:
        candidates = [(name, item) for name, item in constraints.items()
                      if item.get("unique") and item.get("columns") == names]
        unconditional = False
        for name, item in candidates:
            definition = index_sql(connection, cursor, table, name) if item.get("index") else None
            if not item.get("index") or (definition and not re.search(r"\bWHERE\b", definition, re.I)):
                unconditional = True
        if not unconditional:
            problems.append(f"unique key differs in {table} ({', '.join(names)})")
    for field in fields.values():
        if field.is_relation and getattr(field, "db_constraint", False):
            target = (field.remote_field.model._meta.db_table, field.target_field.column)
            if not any(item.get("columns") == [field.column] and item.get("foreign_key") == target for item in values):
                problems.append(f"foreign key differs in {table}.{field.column}")
    return problems


def declared_problems(connection, cursor, model, constraints):
    table = model._meta.db_table
    editor = connection.schema_editor()
    problems = []
    for rule in model._meta.constraints:
        actual = constraints.get(rule.name)
        kind = "check" if isinstance(rule, models.CheckConstraint) else "unique"
        if not actual or not actual.get(kind):
            problems.append(f"missing or different constraint {rule.name}")
            continue
        if isinstance(rule, models.CheckConstraint):
            definition = check_sql(connection, cursor, table, rule.name)
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
            definition = index_sql(connection, cursor, table, rule.name)
            if not index_matches(definition, expected):
                problems.append(f"conditional unique key differs for {rule.name}")
    return problems


def index_problems(connection, cursor, model, constraints):
    table = model._meta.db_table
    editor = connection.schema_editor()
    problems = []
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
            definition = index_sql(connection, cursor, table, index.name)
            if not index_matches(definition, expected):
                problems.append(f"index expression/condition differs for {index.name}")
    return problems
