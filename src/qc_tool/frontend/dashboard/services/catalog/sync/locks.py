"""Database-level serialization for catalog publication."""

from django.db import connection


CATALOG_ADVISORY_LOCK_ID = 684625821927764738


def lock_catalog_sync():
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(%s)",
            [CATALOG_ADVISORY_LOCK_ID],
        )
