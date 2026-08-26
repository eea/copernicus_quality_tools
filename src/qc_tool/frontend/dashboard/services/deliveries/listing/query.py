"""Access-scoped delivery table query and row projection."""

from django.db import connection
from qc_tool.frontend.accounts.authorization import access_for
from qc_tool.frontend.dashboard.access import delivery_action_capabilities
from qc_tool.frontend.dashboard.services.deliveries.listing.statuses import (
    classify_delivery_status,
)
from qc_tool.frontend.dashboard.services.deliveries.listing.statuses import (
    delivery_status_sql,
)

from qc_tool.frontend.dashboard.services.deliveries.listing.filters import (
    MAX_DELIVERY_OFFSET,
    MAX_DELIVERY_PAGE_SIZE,
    bounded_query_integer,
    parse_filter,
)


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
    # Retrieve a table of deliveries.
    # If a delivery has one or more jobs, show information about the job with latest date_created.
    column_lookup = {
        "id": "d.id",
        "name": "d.id",
        "type": "d.s3_id",
        "filename": "d.filename",
        "date_uploaded": "d.date_uploaded",
        "size_bytes": "d.size_bytes",
        "product_ident": "d.product_ident",
        "product_description": "d.product_description",
        "aoi_code": "d.aoi_code",
        "date_submitted": "d.date_submitted",
        "is_deleted": "d.is_deleted",
        "product_ident": "d.product_ident",
        "date_submitted": "d.date_submitted",
        "date_created": "j.date_created",
        "date_started": "j.date_started",
        "date_finished": "j.date_finished",
        "last_job_status": "j.job_status",
        "last_job_uuid": "j.job_uuid",
        "username": "u.username",
        "user": "u.username"}

    # Lookup sort column, if not found then sort by id (default)
    sort_column = column_lookup.get(sort, "d.id")

    # Order asc or desc, must be asc or desc, default is desc
    order = order.strip().lower()
    if order not in ("asc", "desc"):
        order = "desc"

    # Assemble SQL filtering and/or searching
    filter_sql = ""
    filter_params = []
    if filter:
        filter_sql, filter_params = parse_filter(filter, column_lookup)

    # searching is done on filename column only.
    search_sql = ""
    search_params = []
    if search:
        search_sql = " AND d.filename LIKE %s"
        search_params.append(f"%{search}%")

    # Assemble SQL queries
    sql = """
        SELECT d.id, d.user_id AS action_owner_id, d.filename, u.username,
        d.date_uploaded, d.size_bytes,
        d.product_ident, d.product_description, d.aoi_code,
        d.date_submitted, d.is_deleted,
        d.s3_id,
        j.job_uuid AS last_job_uuid,
        j.date_created, j.date_started, j.date_finished,
        j.job_status as last_job_status,
        up.country AS user_country
        FROM dashboard_delivery d
        LEFT JOIN dashboard_job j
        ON j.job_uuid = (
          SELECT job_uuid FROM dashboard_job j
          WHERE j.delivery_id = d.id
          ORDER BY j.date_created DESC, j.job_uuid DESC LIMIT 1)
        INNER JOIN auth_user u
        ON d.user_id = u.id
        LEFT JOIN dashboard_userprofile up
        ON d.user_id = up.user_id
        WHERE d.is_deleted = FALSE
        """
    sql_total = """
        SELECT COUNT(d.id)
        FROM dashboard_delivery d
        LEFT JOIN dashboard_job j
        ON j.job_uuid = (
          SELECT job_uuid FROM dashboard_job j
          WHERE j.delivery_id = d.id
          ORDER BY j.date_created DESC, j.job_uuid DESC LIMIT 1)
        INNER JOIN auth_user u
        ON d.user_id = u.id
        LEFT JOIN dashboard_userprofile up
        ON d.user_id = up.user_id
        WHERE d.is_deleted = FALSE
        """

    account_access = account_access or access_for(user)
    visibility_params = []

    if not account_access.is_administrator:
        visibility_clauses = ["d.user_id = %s"]
        visibility_params.append(user.id)
        if account_access.can_view_region_deliveries:
            # AOI metadata is uploader-influenced until every product has an
            # authoritative spatial validator. Keep authorization on the
            # existing legacy region contract during that trust transition.
            region_codes = sorted(account_access.region_codes)
            placeholders = ", ".join(["%s"] * len(region_codes))
            visibility_clauses.append(
                f"up.country IN ({placeholders})"
            )
            visibility_params.extend(region_codes)
        if account_access.can_view_product_deliveries:
            product_idents = sorted(account_access.product_idents)
            placeholders = ", ".join(["%s"] * len(product_idents))
            visibility_clauses.append(
                f"LOWER(d.product_ident) IN ({placeholders})"
            )
            visibility_params.extend(product_idents)

        visibility_sql = " AND ({})".format(
            " OR ".join(visibility_clauses)
        )
        sql += visibility_sql
        sql_total += visibility_sql

    status_sql, status_params = delivery_status_sql(delivery_status)
    sql += status_sql
    sql_total += status_sql

    # Add filter expression and search expressions to sql queries
    sql_total += filter_sql
    sql_total += search_sql
    sql += filter_sql
    sql += search_sql
    query_params = (
        visibility_params + status_params + filter_params + search_params
    )

    # Add sort, offset and limit to sql query (with assigned or default values)
    sql += f" ORDER BY {sort_column} {order} LIMIT {limit} OFFSET {offset};"

    with connection.cursor() as cursor:
        # fetch total rows
        cursor.execute(sql_total, query_params)
        total_result = cursor.fetchone()
        total = int(total_result[0])

        # fetch query results
        cursor.execute(sql, query_params)

        # arrange the results
        header = [i[0] for i in cursor.description]
        rows = cursor.fetchall()
        data = []
        for row in rows:
            data.append(dict(zip(header, row)))

        # Add calculated "type" column to indicate if the file is local upload or s3.
        for item in data:
            if item["s3_id"]:
                item["type"] = "s3"
            else:
                item["type"] = "local"
            owner_id = item.pop("action_owner_id")
            if include_capabilities:
                item.update(
                    delivery_action_capabilities(account_access, owner_id)
                )
            if "last_job_status" in item:
                item["delivery_status"] = classify_delivery_status(
                    item["last_job_status"],
                    item.get("date_submitted"),
                ).value
        return total, data
