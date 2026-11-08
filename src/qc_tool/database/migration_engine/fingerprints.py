"""Stable physical-schema evidence used by migration review."""

import hashlib
import json

from django.core.management.base import CommandError

from qc_tool.database.predicates import predicate_signature
from .postgres_catalog import schema_queries


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def schema_fingerprint(connection):
    """Fingerprint inspected physical schema; exclude row and sequence values."""
    catalog = []
    with connection.cursor() as cursor:
        if connection.vendor == "sqlite":
            cursor.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")
            catalog = cursor.fetchall()
        elif connection.vendor == "postgresql":
            for query in schema_queries():
                cursor.execute(query)
                rows = cursor.fetchall()
                if "pg_get_constraintdef" in query:
                    normalized = []
                    for namespace_name, table, name, definition, validated in rows:
                        if definition.startswith("CHECK "):
                            try:
                                definition = predicate_signature(definition)
                            except ValueError:
                                pass
                        normalized.append((namespace_name, table, name, definition, validated))
                    rows = normalized
                catalog.append(rows)
        else:
            raise CommandError("Managed migration inspection supports PostgreSQL and SQLite only.")
    return digest(catalog)
