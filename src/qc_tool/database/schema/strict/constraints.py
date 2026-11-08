"""Reject extra constraints and indexes before accepting an upgrade source."""

from collections import Counter
from ..catalog import check_sql, index_sql
from ..signatures import check_signature, index_signature


def problems(connection, cursor, model, constraints):
    """Reject unmodelled objects before accepting a supported source.

    Adoption must not silently bless extra constraints, indexes, triggers,
    generated/default expressions or row-security policies. Privileges and
    ownership are handled by the existing native-restore policy separately.
    """
    table = model._meta.db_table
    problems = []
    editor = connection.schema_editor()
    declared = {rule.name for rule in model._meta.constraints}
    unique = Counter((field.column,) for field in model._meta.local_fields if field.unique and not field.primary_key)
    unique.update(tuple(model._meta.get_field(name).column for name in names)
                  for names in model._meta.unique_together)
    relations = Counter((field.column, field.remote_field.model._meta.db_table, field.target_field.column)
                 for field in model._meta.local_fields
                 if field.is_relation and getattr(field, "db_constraint", False))
    expected_indexes = list(editor._model_indexes_sql(model))
    index_signatures = Counter(index_signature(str(index)) for index in expected_indexes)
    checks = []
    for field in model._meta.local_fields:
        check = field.db_parameters(connection).get("check")
        if check:
            try:
                checks.append(check_signature(check % {"column": connection.ops.quote_name(field.column)}))
            except (ValueError, TypeError):
                problems.append(f"cannot verify generated check in {table}.{field.column}")
    generated_checks = Counter(checks)
    for name, value in constraints.items():
        if name in declared:
            continue
        columns = tuple(value.get("columns") or ())
        if value.get("primary_key"):
            if columns != (model._meta.pk.column,):
                problems.append(f"unexpected primary constraint {table}.{name}")
        elif value.get("unique"):
            unique[columns] -= 1
            if unique[columns] < 0 or value.get("condition"):
                problems.append(f"unexpected unique/primary constraint {table}.{name}")
        elif value.get("foreign_key"):
            signature = (columns[0], *value["foreign_key"]) if len(columns) == 1 else ()
            relations[signature] -= 1
            if relations[signature] < 0:
                problems.append(f"unexpected foreign key {table}.{name}")
        elif value.get("check"):
            if connection.vendor == "sqlite":
                # SQLite does not retain names for field-generated checks;
                # compare every table CHECK body below instead.
                continue
            definition = check_sql(connection, cursor, table, name)
            try:
                signature = check_signature(definition or "")
                generated_checks[signature] -= 1
                if generated_checks[signature] < 0:
                    problems.append(f"unexpected check constraint {table}.{name}")
            except ValueError:
                problems.append(f"unverifiable check constraint {table}.{name}")
        elif value.get("index"):
            actual = index_sql(connection, cursor, table, name)
            signature = index_signature(actual) if actual else None
            index_signatures[signature] -= 1
            if signature is None or index_signatures[signature] < 0:
                problems.append(f"unexpected index {table}.{name}")
        else:
            problems.append(f"unexpected constraint {table}.{name}")
    return problems, checks, generated_checks
