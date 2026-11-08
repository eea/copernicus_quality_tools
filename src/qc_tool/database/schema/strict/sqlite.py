"""Inspect SQLite checks, defaults, generated columns and collations strictly."""

from collections import Counter
import re
from django.db import models
from ..catalog import table_sql
from ..expressions import declared_expression_matches
from ..signatures import check_signature
from ..sqlite import checks, column_sql, generated_expression


def problems(connection, cursor, model, field_checks):
    table = model._meta.db_table
    editor = connection.schema_editor()
    problems = []
    field_checks += [check_signature(rule._get_check_sql(model, editor)) for rule in model._meta.constraints
               if isinstance(rule, models.CheckConstraint)]
    expected_checks = Counter(field_checks)
    for body in checks(table_sql(cursor, table)):
        try:
            signature = check_signature(body)
            expected_checks[signature] -= 1
            if expected_checks[signature] < 0:
                problems.append(f"unexpected check expression in {table}")
        except ValueError:
            problems.append(f"unverifiable check expression in {table}")
    if any(count > 0 for count in expected_checks.values()):
        problems.append(f"missing generated check expression in {table}")
    if re.search(r"\bCOLLATE\b", table_sql(cursor, table), re.I) and not any(
            getattr(field, "db_collation", None) for field in model._meta.local_fields):
        problems.append(f"unexpected column collation in {table}")
    fields = {field.column: field for field in model._meta.local_fields}
    cursor.execute("PRAGMA table_xinfo(%s)" % connection.ops.quote_name(table))
    generated_columns = {row[1]: row[6] for row in cursor.fetchall() if len(row) > 6 and row[6] in {2, 3}}
    for column in connection.introspection.get_table_description(cursor, table):
        field = fields.get(column.name)
        if field is None:
            continue
        if column.default is not None and not field.has_db_default():
            problems.append(f"unexpected database default {table}.{column.name}")
        elif field.has_db_default() and not declared_expression_matches(field, column.default, editor):
            problems.append(f"database default expression differs in {table}.{column.name}")
        if getattr(field, "generated", False):
            expected_kind = 3 if field.db_persist else 2
            actual = generated_expression(column_sql(table_sql(cursor, table), column.name))
            if generated_columns.get(column.name) != expected_kind or not declared_expression_matches(field, actual, editor, generated=True):
                problems.append(f"generated expression differs in {table}.{column.name}")
        elif column.name in generated_columns:
            problems.append(f"unexpected generated expression {table}.{column.name}")
    return problems
