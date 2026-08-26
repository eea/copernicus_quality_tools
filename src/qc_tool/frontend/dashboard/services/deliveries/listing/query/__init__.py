"""Stable facade for access-scoped delivery table queries.

``access_for`` and ``connection`` intentionally live in this module because
older integrations patch those names while exercising ``query_deliveries``.
"""

from django.db import connection

from qc_tool.frontend.accounts.authorization import access_for

from .service import execute_delivery_query


def query_deliveries(
    user,
    offset=0,
    limit=20,
    sort="id",
    order="desc",
    filter="",
    search="",
    include_capabilities=False,
    account_access=None,
    delivery_status="all",
):
    """Return the total and projected rows visible to ``user``."""

    return execute_delivery_query(
        user,
        offset=offset,
        limit=limit,
        sort=sort,
        order=order,
        filter_expression=filter,
        search=search,
        include_capabilities=include_capabilities,
        account_access=account_access,
        delivery_status=delivery_status,
        resolve_access=access_for,
        database_connection=connection,
    )


__all__ = ("query_deliveries",)
