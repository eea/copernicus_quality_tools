"""Stable route entry points for the migration administration task."""

from .endpoints import migration_status, migrations

__all__ = ["migration_status", "migrations"]
