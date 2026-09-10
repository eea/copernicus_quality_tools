"""Database-level serialization for catalog publication."""

from django.db import connection

from ..errors import CatalogError


CATALOG_ADVISORY_LOCK_ID = 684625821927764738


def lock_catalog_sync(*, wait=True):
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        if wait:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s)",
                [CATALOG_ADVISORY_LOCK_ID],
            )
        else:
            cursor.execute(
                "SELECT pg_try_advisory_xact_lock(%s)",
                [CATALOG_ADVISORY_LOCK_ID],
            )
            if not cursor.fetchone()[0]:
                raise CatalogError(
                    "catalog_busy",
                    "The product catalog is being updated. Please retry shortly.",
                )
