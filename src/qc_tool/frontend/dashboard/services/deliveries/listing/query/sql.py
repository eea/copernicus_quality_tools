"""Static SQL assembly for access-scoped delivery listings."""

from dataclasses import dataclass

from django.contrib.auth import get_user_model

from qc_tool.frontend.accounts.models import UserProfile
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.dashboard.models import Product, ProductRelease
from qc_tool.frontend.dashboard.services.deliveries.listing.filters import (
    parse_filter,
)
from qc_tool.frontend.dashboard.services.deliveries.listing.statuses import (
    delivery_status_sql,
)

from .columns import COLUMN_LOOKUP


def _delivery_join_sql(database_connection):
    """Resolve SQL identifiers from the same models used by ORM consumers."""

    quote_name = database_connection.ops.quote_name
    delivery_table = quote_name(Delivery._meta.db_table)
    job_table = quote_name(Job._meta.db_table)
    user_table = quote_name(get_user_model()._meta.db_table)
    profile_table = quote_name(UserProfile._meta.db_table)
    return f"""
        FROM {delivery_table} d
        LEFT JOIN {job_table} j
        ON j.job_uuid = (
          SELECT job_uuid FROM {job_table} j
          WHERE j.delivery_id = d.id
          ORDER BY j.date_created DESC, j.job_uuid DESC LIMIT 1)
        INNER JOIN {user_table} u
        ON d.user_id = u.id
        LEFT JOIN {profile_table} up
        ON d.user_id = up.user_id
        WHERE d.is_deleted = FALSE
        """


DELIVERY_SELECT_SQL = """
        SELECT d.id, d.user_id AS action_owner_id, d.filename, u.username,
        d.date_uploaded, d.size_bytes,
        d.product_ident, d.product_description, d.aoi_code,
        d.aoi_code_submitted, d.content_sha256,
        d.date_submitted, d.is_deleted,
        d.s3_id,
        j.job_uuid AS last_job_uuid,
        j.date_created, j.date_started, j.date_finished,
        j.job_status as last_job_status,
        up.country AS user_country
        """


@dataclass(frozen=True)
class DeliveryQueryPlan:
    count_sql: str
    rows_sql: str
    parameters: list


def build_delivery_query_plan(
    *,
    user_id,
    account_access,
    offset,
    limit,
    sort,
    order,
    filter_expression,
    search,
    delivery_status,
    database_connection,
):
    """Build parameterized count and row statements for one list request."""

    sort_column = COLUMN_LOOKUP.get(sort, "d.id")
    normalized_order = order.strip().lower()
    if normalized_order not in ("asc", "desc"):
        normalized_order = "desc"

    filter_sql = ""
    filter_parameters = []
    if filter_expression:
        filter_sql, filter_parameters = parse_filter(
            filter_expression,
            COLUMN_LOOKUP,
        )

    search_sql = ""
    search_parameters = []
    if search:
        search_sql = " AND d.filename LIKE %s"
        search_parameters.append(f"%{search}%")

    visibility_sql, visibility_parameters = _visibility_clause(
        user_id,
        account_access,
        database_connection,
    )
    status_sql, status_parameters = delivery_status_sql(delivery_status)
    constraints = visibility_sql + status_sql + filter_sql + search_sql
    join_sql = _delivery_join_sql(database_connection)
    parameters = (
        visibility_parameters
        + status_parameters
        + filter_parameters
        + search_parameters
    )

    return DeliveryQueryPlan(
        count_sql="SELECT COUNT(d.id)" + join_sql + constraints,
        rows_sql=(
            DELIVERY_SELECT_SQL
            + join_sql
            + constraints
            + f" ORDER BY {sort_column} {normalized_order}"
            + f" LIMIT {limit} OFFSET {offset};"
        ),
        parameters=parameters,
    )


def _visibility_clause(user_id, account_access, database_connection):
    if account_access.is_administrator:
        return "", []

    clauses = ["d.user_id = %s"]
    parameters = [user_id]
    if account_access.can_view_region_deliveries:
        region_codes = sorted(account_access.region_codes)
        placeholders = ", ".join(["%s"] * len(region_codes))
        clauses.append(f"up.country IN ({placeholders})")
        parameters.extend(region_codes)
    if account_access.can_view_product_deliveries:
        product_idents = sorted(account_access.product_idents)
        placeholders = ", ".join(["%s"] * len(product_idents))
        clauses.append(f"LOWER(d.product_ident) IN ({placeholders})")
        parameters.extend(product_idents)
        quote_name = database_connection.ops.quote_name
        release_table = quote_name(ProductRelease._meta.db_table)
        product_table = quote_name(Product._meta.db_table)
        clauses.append(
            f"EXISTS (SELECT 1 FROM {release_table} scoped_release "
            f"JOIN {product_table} scoped_product ON scoped_product.id = scoped_release.product_id "
            f"WHERE scoped_release.id = j.product_release_id "
            f"AND scoped_product.ident IN ({placeholders}))"
        )
        parameters.extend(product_idents)

    return " AND ({})".format(" OR ".join(clauses)), parameters
