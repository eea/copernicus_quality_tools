"""Static SQL assembly for access-scoped delivery listings."""

from dataclasses import dataclass

from django.contrib.auth import get_user_model

from qc_tool.frontend.accounts.models import UserProfile
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import DeliverySubmission, SubmissionReviewEvent
from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.dashboard.models import Product, ProductRelease
from qc_tool.frontend.dashboard.services.deliveries.listing.filters import (
    parse_filter,
)
from qc_tool.frontend.dashboard.services.deliveries.listing.statuses import (
    delivery_status_sql,
)
from qc_tool.frontend.dashboard.services.deliveries.listing.workflows import (
    DeliveryWorkflow, delivery_priority_sql, delivery_workflow_sql, parse_delivery_workflow,
)

from .columns import COLUMN_LOOKUP


def _delivery_join_sql(database_connection, submission_join):
    """Resolve SQL identifiers from the same models used by ORM consumers."""

    quote_name = database_connection.ops.quote_name
    delivery_table = quote_name(Delivery._meta.db_table)
    job_table = quote_name(Job._meta.db_table)
    user_table = quote_name(get_user_model()._meta.db_table)
    profile_table = quote_name(UserProfile._meta.db_table)
    release_table = quote_name(ProductRelease._meta.db_table)
    product_table = quote_name(Product._meta.db_table)
    return f"""
        FROM {delivery_table} d
        LEFT JOIN {job_table} j
        ON j.job_uuid = (
          SELECT job_uuid FROM {job_table} j
          WHERE j.delivery_id = d.id
          ORDER BY j.date_created DESC, j.job_uuid DESC LIMIT 1)
        LEFT JOIN {release_table} scoped_release
        ON scoped_release.id = j.product_release_id
        LEFT JOIN {product_table} scoped_product
        ON scoped_product.id = scoped_release.product_id
        INNER JOIN {user_table} u
        ON d.user_id = u.id
        LEFT JOIN {profile_table} up
        ON d.user_id = up.user_id
        {submission_join}
        WHERE d.is_deleted = FALSE
        """


def _submission_join_sql(database_connection, account_access, user_id):
    """Join only review receipts visible to the owner or assigned reviewers.

    A region grant can reveal a delivery without granting access to its manager
    correspondence. Keep that boundary in SQL so filters cannot disclose it.
    """

    quote_name = database_connection.ops.quote_name
    submission_table = quote_name(DeliverySubmission._meta.db_table)
    event_table = quote_name(SubmissionReviewEvent._meta.db_table)
    visibility = ""
    parameters = []
    if not account_access.is_administrator:
        clauses = ["FALSE"]
        release_table = quote_name(ProductRelease._meta.db_table)
        product_table = quote_name(Product._meta.db_table)
        owner_products = sorted(account_access.product_idents)
        if owner_products:
            placeholders = ", ".join(["%s"] * len(owner_products))
            job_table = quote_name(Job._meta.db_table)
            clauses = [
                "(d.user_id = %s AND EXISTS ("
                f"SELECT 1 FROM {job_table} submission_job "
                f"JOIN {release_table} owner_release "
                "ON owner_release.id = s.product_release_id "
                f"JOIN {product_table} owner_product "
                "ON owner_product.id = owner_release.product_id "
                "WHERE submission_job.job_uuid = s.job_id AND ("
                f"LOWER(TRIM(submission_job.product_ident)) IN ({placeholders}) "
                f"OR LOWER(TRIM(owner_product.ident)) IN ({placeholders}))))"
            ]
            parameters.extend([user_id] + owner_products * 2)
        if getattr(account_access, "is_product_manager", False):
            products = sorted(account_access.reviewable_product_idents)
            if products:
                placeholders = ", ".join(["%s"] * len(products))
                clauses.append(
                    f"EXISTS (SELECT 1 FROM {release_table} review_release "
                    f"JOIN {product_table} review_product "
                    f"ON review_product.id = review_release.product_id "
                    f"WHERE review_release.id = s.product_release_id "
                    f"AND review_product.ident IN ({placeholders}))"
                )
                parameters.extend(products)
        visibility = " AND ({})".format(" OR ".join(clauses))
    return (
        f"LEFT JOIN {submission_table} s ON s.delivery_id = d.id {visibility} "
        f"LEFT JOIN {event_table} review_event "
        "ON review_event.submission_id = s.submission_uuid "
        "AND review_event.version = s.review_version "
        "AND ((s.review_state = 'accepted' AND review_event.decision = 'approved') "
        "OR (s.review_state = 'rejected' AND review_event.decision = 'declined'))",
        parameters,
    )


DELIVERY_SELECT_SQL = """
        SELECT d.id, d.user_id AS action_owner_id, d.filename, u.username,
        d.date_uploaded, d.size_bytes,
        d.product_ident, d.product_description, d.aoi_code,
        d.aoi_code_submitted, d.content_sha256,
        d.date_submitted, d.is_deleted,
        d.s3_id,
        j.job_uuid AS last_job_uuid,
        j.product_ident AS action_job_product_ident,
        scoped_product.ident AS action_catalog_product_ident,
        j.date_created, j.date_started, j.date_finished,
        j.job_status as last_job_status,
        up.country AS user_country,
        s.submission_uuid AS submission_id,
        s.review_state AS submission_review_state,
        s.publication_state AS submission_publication_state,
        review_event.notes AS review_notes,
        review_event.actor_username AS review_actor_username,
        review_event.created_at AS review_created_at
        """


@dataclass(frozen=True)
class DeliveryQueryPlan:
    count_sql: str
    rows_sql: str
    parameters: list
    row_parameters: list


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
    delivery_view,
    database_connection,
):
    """Build parameterized count and row statements for one list request."""

    delivery_view = parse_delivery_workflow(delivery_view)
    sort_column = COLUMN_LOOKUP.get(sort, "d.id")
    normalized_order = order.strip().lower()
    if normalized_order not in ("asc", "desc"):
        normalized_order = "desc"

    sort_parameters = []
    if sort == "priority" or delivery_view is DeliveryWorkflow.ACTION_REQUIRED:
        priority_sql, sort_parameters = delivery_priority_sql()
        ordering_sql = f"{priority_sql} ASC"
        if sort != "priority":
            ordering_sql += f", {sort_column} {normalized_order}"
        if sort == "priority" or sort_column != "d.id":
            ordering_sql += ", d.id DESC"
    else:
        ordering_sql = f"{sort_column} {normalized_order}"
        if sort_column != "d.id":
            ordering_sql += ", d.id DESC"

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
    workflow_sql, workflow_parameters = delivery_workflow_sql(delivery_view)
    constraints = visibility_sql + workflow_sql + status_sql + filter_sql + search_sql
    submission_join, submission_parameters = _submission_join_sql(
        database_connection, account_access, user_id,
    )
    join_sql = _delivery_join_sql(database_connection, submission_join)
    parameters = (
        submission_parameters
        + visibility_parameters
        + workflow_parameters
        + status_parameters
        + filter_parameters
        + search_parameters
    )
    # Only the internal export iterator omits pagination. HTTP list callers
    # still supply bounded integers through execute_delivery_query.
    pagination_sql = f" LIMIT {limit} OFFSET {offset}" if limit is not None else ""

    return DeliveryQueryPlan(
        count_sql="SELECT COUNT(d.id)" + join_sql + constraints,
        rows_sql=(
            DELIVERY_SELECT_SQL
            + join_sql
            + constraints
            + f" ORDER BY {ordering_sql}"
            + pagination_sql + ";"
        ),
        parameters=parameters,
        row_parameters=parameters + sort_parameters,
    )


def _visibility_clause(user_id, account_access, database_connection):
    if account_access.is_administrator:
        return "", []

    product_sql, product_parameters = _product_scope_clause(account_access)
    owner_scope_sql = product_sql
    if account_access.product_idents:
        owner_scope_sql += (
            " OR (NULLIF(TRIM(d.product_ident), '') IS NULL AND j.job_uuid IS NULL)"
        )
    clauses = [f"(d.user_id = %s AND ({owner_scope_sql}))"]
    parameters = [user_id] + product_parameters
    if account_access.can_view_region_deliveries:
        region_codes = sorted(account_access.region_codes)
        placeholders = ", ".join(["%s"] * len(region_codes))
        clauses.append(f"up.country IN ({placeholders})")
        parameters.extend(region_codes)
    if account_access.can_view_product_deliveries:
        clauses.append(f"({product_sql})")
        parameters.extend(product_parameters)

    return " AND ({})".format(" OR ".join(clauses)), parameters


def _product_scope_clause(account_access):
    product_idents = sorted(account_access.product_idents)
    if not product_idents:
        return "FALSE", []
    placeholders = ", ".join(["%s"] * len(product_idents))
    clauses = [
        f"LOWER(TRIM(d.product_ident)) IN ({placeholders})",
        f"LOWER(TRIM(scoped_product.ident)) IN ({placeholders})",
        "(NULLIF(TRIM(d.product_ident), '') IS NULL "
        f"AND LOWER(TRIM(j.product_ident)) IN ({placeholders}))",
    ]
    parameters = product_idents * 3
    derived_idents = sorted(account_access.operable_product_idents - account_access.product_idents)
    if derived_idents:
        placeholders = ", ".join(["%s"] * len(derived_idents))
        clauses.append(
            "(j.job_uuid IS NULL "
            f"AND LOWER(TRIM(d.product_ident)) IN ({placeholders}))"
        )
        parameters.extend(derived_idents)
    return " OR ".join(clauses), parameters
