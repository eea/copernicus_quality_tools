"""Prevent incidental ORM mutations while the workspace remains browsable."""

from contextlib import contextmanager, ExitStack
import re

from django.db import connections, transaction
import sqlparse
from sqlparse import tokens

from .state import MaintenanceError


class MaintenanceWriteBlocked(MaintenanceError):
    """An ostensibly read-only view attempted to persist a database change."""


_SQLITE_SCHEMA_READ = re.compile(
    r'\s*PRAGMA\s+(?:table_info|table_xinfo|index_list|index_info|foreign_key_list)'
    r'\s*\(\s*"(?:[^"\x00]|"")*"\s*\)\s*;?\s*',
    re.IGNORECASE,
)


def _sqlite_schema_read(sql, context):
    # Django quotes table/index identifiers in its SQLite inspector. Permit
    # only its metadata-reading forms, never assignments, arbitrary PRAGMAs
    # or a second statement. Names remain confined to one quoted argument.
    return (
        getattr(context.get("connection"), "vendor", None) == "sqlite"
        and _SQLITE_SCHEMA_READ.fullmatch(sql) is not None
    )


def _read_query(execute, sql, params, many, context):
    # This guards the application's own ORM/query paths, not arbitrary SQL
    # from untrusted clients. No application endpoint accepts arbitrary SQL.
    statements = sqlparse.parse(sql)
    allowed = len(statements) == 1
    if allowed:
        statement = statements[0]
        first = statement.token_first(skip_cm=True)
        first_word = first.value.split()[0].upper() if first is not None else ""
        transaction = first_word in {"BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE"}
        read = statement.get_type() == "SELECT" or first_word in {"SHOW", "EXPLAIN"}
        modifying = any(
            token.ttype in tokens.Keyword.DDL
            # PostgreSQL SELECT ... INTO creates a persistent table although
            # sqlparse classifies the statement itself as SELECT.
            or (token.ttype in tokens.Keyword and token.normalized == "INTO")
            or (
                token.ttype in tokens.Keyword.DML
                and token.normalized not in (
                    {"SELECT", "COMMIT", "ROLLBACK"} if transaction else {"SELECT"}
                )
            )
            for token in statement.flatten()
        )
        # SQL parsers classify savepoint rollback as DML. Transaction control
        # must remain available so a rejected ORM update can be rolled back.
        allowed = (transaction or read or _sqlite_schema_read(sql, context)) and not modifying
    if not allowed:
        raise MaintenanceWriteBlocked("Changes are temporarily unavailable during maintenance.")
    return execute(sql, params, many, context)


@contextmanager
def read_only_database_access():
    """Install Django's public query wrapper on this request's connections."""
    with ExitStack() as stack:
        for connection in connections.all():
            stack.enter_context(connection.execute_wrapper(_read_query))
            # ORM updates mark an enclosing transaction for rollback even
            # when the wrapper rejected SQL before execution. Own a savepoint
            # when embedded in one, so the rejection cannot poison its caller.
            if connection.in_atomic_block:
                stack.enter_context(transaction.atomic(using=connection.alias))
        yield


class ReadOnlyStream:
    """Scope the guard per stream step, never to an idle thread between calls."""

    def __init__(self, content):
        self._content = iter(content)

    def __iter__(self):
        return self

    def __next__(self):
        with read_only_database_access():
            try:
                return next(self._content)
            except StopIteration:
                # Exhaustion is normal completion, not a transaction failure.
                pass
        raise StopIteration
