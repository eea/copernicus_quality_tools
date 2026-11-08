"""Compare declared field columns without changing the inspected database."""

import re
from django.db import models
from .catalog import column_types

# Preserve both reviewed implicit Django join-ID widths without rewriting IDs.
AUTH_JOIN_TABLES = frozenset({"auth_group_permissions", "auth_user_groups", "auth_user_user_permissions"})

def native_type(value, vendor):
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

def problems(connection, cursor, model):
    table = model._meta.db_table
    description = connection.introspection.get_table_description(cursor, table)
    columns = {column.name: column for column in description}
    fields = {field.column: field for field in model._meta.local_fields}
    problems = []
    if columns.keys() != fields.keys():
        problems.append(f"columns differ in {table}")
    types = column_types(connection, cursor, table, description)
    for name in columns.keys() & fields.keys():
        field = fields[name]
        actual_type = native_type(types[name], connection.vendor)
        expected_type = native_type(field.db_type(connection), connection.vendor)
        if table in AUTH_JOIN_TABLES and name == "id" and connection.vendor == "postgresql":
            allowed_types = {"integer", "bigint"}
        else:
            allowed_types = {expected_type}
        if actual_type not in allowed_types:
            problems.append(f"column type differs in {table}.{name}")
        # Django emits a GENERATED clause instead of NOT NULL for these
        # fields. Match its physical schema, not model validation flags.
        expected_null = bool(field.null or getattr(field, "generated", False))
        if bool(columns[name].null_ok) != expected_null:
            problems.append(f"column nullability differs in {table}.{name}")
        if (connection.vendor == "sqlite" and isinstance(field, models.JSONField)
                and not getattr(columns[name], "has_json_constraint", False)):
            problems.append(f"JSON validation differs in {table}.{name}")
    return problems
