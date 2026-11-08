"""Inspect PostgreSQL expressions, row security and foreign-key behavior strictly."""

from django.db import models
from ..expressions import declared_expression_matches


def problems(connection, cursor, model, generated_checks):
    table = model._meta.db_table
    editor = connection.schema_editor()
    problems = []
    cursor.execute("SELECT a.attname,a.attgenerated,pg_get_expr(d.adbin,d.adrelid),c.collname "
                   "FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum "
                   "LEFT JOIN pg_collation c ON c.oid=a.attcollation "
                   "WHERE a.attrelid=%s::regclass AND a.attnum>0 AND NOT a.attisdropped", [table])
    fields = {field.column: field for field in model._meta.local_fields}
    for name, generated, default, collation in cursor.fetchall():
        field = fields.get(name)
        if field is not None and getattr(field, "generated", False):
            expected_kind = "s" if field.db_persist else "v"
            if generated != expected_kind or not declared_expression_matches(field, default, editor, generated=True):
                problems.append(f"generated expression differs in {table}.{name}")
        elif generated:
            problems.append(f"unexpected generated/default expression {table}.{name}")
        elif field is not None and field.has_db_default():
            if not declared_expression_matches(field, default, editor):
                problems.append(f"database default expression differs in {table}.{name}")
        elif (default is not None and field is not None
              and not isinstance(field, (models.AutoField, models.BigAutoField, models.SmallAutoField))):
            problems.append(f"unexpected generated/default expression {table}.{name}")
        if field is not None and collation not in {None, getattr(field, "db_collation", None) or "default"}:
            problems.append(f"column collation differs in {table}.{name}")
    cursor.execute("SELECT relrowsecurity,relforcerowsecurity,relkind,relpersistence "
                   "FROM pg_class WHERE oid=%s::regclass", [table])
    row = cursor.fetchone()
    if row and row != (False, False, "r", "p"):
        problems.append(f"unexpected row security, partitioning or persistence in {table}")
    cursor.execute("SELECT conname FROM pg_constraint WHERE conrelid=%s::regclass AND contype='f' "
                   "AND (NOT condeferrable OR NOT condeferred OR confupdtype<>'a' OR confdeltype<>'a' OR confmatchtype<>'s')", [table])
    problems += [f"foreign key behavior differs in {table}.{name}" for (name,) in cursor.fetchall()]
    if any(count > 0 for count in generated_checks.values()):
        problems.append(f"missing generated check constraint in {table}")
    return problems
