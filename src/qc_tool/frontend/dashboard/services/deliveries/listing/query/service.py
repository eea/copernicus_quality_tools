"""Execution boundary for delivery-list SQL plans."""

from qc_tool.frontend.dashboard.services.deliveries.listing.filters import (
    bounded_query_integer,
)
from qc_tool.frontend.dashboard.services.deliveries.listing.filters import (
    MAX_DELIVERY_OFFSET,
)
from qc_tool.frontend.dashboard.services.deliveries.listing.filters import (
    MAX_DELIVERY_PAGE_SIZE,
)

from .projection import project_delivery_rows
from .projection import rows_from_cursor
from .sql import build_delivery_query_plan


def execute_delivery_query(
    user,
    *,
    offset,
    limit,
    sort,
    order,
    filter_expression,
    search,
    include_capabilities,
    account_access,
    delivery_status,
    resolve_access,
    database_connection,
):
    """Execute a bounded delivery-list plan and project its public rows."""

    offset = bounded_query_integer(
        offset,
        default=0,
        minimum=0,
        maximum=MAX_DELIVERY_OFFSET,
    )
    limit = bounded_query_integer(
        limit,
        default=20,
        minimum=0,
        maximum=MAX_DELIVERY_PAGE_SIZE,
    )
    account_access = account_access or resolve_access(user)
    plan = build_delivery_query_plan(
        user_id=user.id,
        account_access=account_access,
        offset=offset,
        limit=limit,
        sort=sort,
        order=order,
        filter_expression=filter_expression,
        search=search,
        delivery_status=delivery_status,
    )

    with database_connection.cursor() as cursor:
        cursor.execute(plan.count_sql, plan.parameters)
        total = int(cursor.fetchone()[0])

        cursor.execute(plan.rows_sql, plan.parameters)
        rows = rows_from_cursor(cursor)

    return total, project_delivery_rows(
        rows,
        account_access,
        include_capabilities,
    )
