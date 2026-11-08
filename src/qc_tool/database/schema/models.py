"""Compose field, key and index inspection for one current or historical model."""

from . import columns, constraints, strict


def problems(connection, cursor, model, *, strict_source=False):
    result = columns.problems(connection, cursor, model)
    declared = connection.introspection.get_constraints(cursor, model._meta.db_table)
    result.extend(constraints.key_problems(connection, cursor, model, declared))
    result.extend(constraints.declared_problems(connection, cursor, model, declared))
    result.extend(constraints.index_problems(connection, cursor, model, declared))
    if strict_source:
        result.extend(strict.model_problems(connection, cursor, model, declared))
    return result
