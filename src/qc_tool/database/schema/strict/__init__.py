"""Strict supported-source checks shared by adoption and managed-history review."""

from . import constraints, postgres, sqlite


def model_problems(connection, cursor, model, declared_constraints):
    problems, field_checks, generated_checks = constraints.problems(
        connection, cursor, model, declared_constraints)
    if connection.vendor == "sqlite":
        problems.extend(sqlite.problems(connection, cursor, model, field_checks))
    if connection.vendor == "postgresql":
        problems.extend(postgres.problems(connection, cursor, model, generated_checks))
    return problems
