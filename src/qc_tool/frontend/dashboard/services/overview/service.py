"""Build a truthful, bounded dashboard snapshot from QC Tool records."""

from collections import defaultdict
from datetime import timedelta

from django.db.models import BooleanField
from django.db.models import Case
from django.db.models import Count
from django.db.models import Max
from django.db.models import Q
from django.db.models import Subquery
from django.db.models import Value
from django.db.models import When
from django.db.models.functions import Coalesce
from django.db.models.functions import Lower
from django.db.models.functions import Trim
from django.utils import timezone

from qc_tool.frontend.dashboard.access.delivery_querysets import visible_deliveries
from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.dashboard.services.deliveries import classify_job_status
from qc_tool.frontend.dashboard.services.deliveries import with_latest_job_status
from qc_tool.frontend.dashboard.services.deliveries.summary import FAILED_STATUSES
from qc_tool.frontend.dashboard.services.deliveries.summary import (
    FILE_NOT_FOUND_STATUS,
)
from qc_tool.frontend.dashboard.services.deliveries.summary import (
    IN_PROGRESS_STATUSES,
)
from qc_tool.common import JOB_OK

from .contracts import ActivityItem
from .contracts import CoverageSegment
from .contracts import DeliveryOverview
from .contracts import ProductAttention
from .contracts import WorkspaceDashboard


DEFAULT_ITEM_LIMIT = 5


def build_workspace_overview(
    account_access,
    *,
    recent_limit=DEFAULT_ITEM_LIMIT,
    product_limit=DEFAULT_ITEM_LIMIT,
):
    """Return dashboard facts restricted to ``account_access``.

    The service intentionally avoids forecasts, target AOIs, trends, and token
    expiry because those concepts do not exist in the current data model.
    """

    _validate_limit(recent_limit)
    _validate_limit(product_limit)
    deliveries = visible_deliveries(account_access)
    summary = _delivery_overview(deliveries)
    return WorkspaceDashboard(
        summary=summary,
        coverage=_coverage_segments(summary),
        product_attention=_product_attention(deliveries, product_limit),
        recent_activity=_recent_activity(
            deliveries,
            account_access=account_access,
            limit=recent_limit,
        ),
    )


def _delivery_overview(deliveries):
    recent_cutoff = timezone.now() - timedelta(days=7)
    grouped = (
        with_latest_job_status(deliveries)
        .annotate(
            dashboard_submitted=Case(
                When(date_submitted__isnull=False, then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            ),
            dashboard_recent=Case(
                When(date_uploaded__gte=recent_cutoff, then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            ),
        )
        .values(
            "latest_job_status",
            "dashboard_submitted",
            "dashboard_recent",
        )
        .annotate(delivery_count=Count("pk"))
    )

    counts = defaultdict(int)
    for row in grouped:
        count = row["delivery_count"]
        category = classify_job_status(row["latest_job_status"])
        counts["total"] += count
        counts[category] += count
        if row["dashboard_submitted"]:
            counts["submitted"] += count
        elif category == "passed":
            counts["ready"] += count
        elif category == "in_progress":
            counts["coverage_in_progress"] += count
        else:
            counts["coverage_attention"] += count
        if row["dashboard_recent"]:
            counts["recent"] += count

    return DeliveryOverview(
        total_deliveries=counts["total"],
        uploaded_last_7_days=counts["recent"],
        qc_passed=counts["passed"],
        qc_in_progress=counts["in_progress"],
        qc_failed=counts["failed"],
        not_checked=counts["not_checked"],
        unknown_status=counts["other"],
        submitted_deliveries=counts["submitted"],
        ready_to_submit=counts["ready"],
        submission_in_progress=counts["coverage_in_progress"],
        coverage_attention=counts["coverage_attention"],
    )


def _coverage_segments(summary):
    values = (
        ("submitted", "Submitted", summary.submitted_deliveries),
        ("ready", "Ready to submit", summary.ready_to_submit),
        (
            "in_progress",
            "QC in progress",
            summary.submission_in_progress,
        ),
        ("blocked", "Needs attention", summary.coverage_attention),
    )
    segments = []
    offset = 0.0
    for key, label, count in values:
        percentage = _percentage(count, summary.total_deliveries)
        segments.append(
            CoverageSegment(
                key=key,
                label=label,
                count=count,
                percentage=percentage,
                offset=round(offset, 4),
            )
        )
        offset += percentage
    return tuple(segments)


def _product_attention(deliveries, limit):
    failed_statuses = tuple(FAILED_STATUSES) + (FILE_NOT_FOUND_STATUS,)
    known_statuses = (JOB_OK,) + tuple(IN_PROGRESS_STATUSES) + failed_statuses
    unknown_status = Q(latest_job_status__isnull=False) & ~Q(
        latest_job_status__in=known_statuses
    )
    attention_status = (
        Q(latest_job_status__isnull=True)
        | Q(latest_job_status__in=failed_statuses)
        | unknown_status
    )
    rows = (
        with_latest_job_status(deliveries)
        .annotate(
            dashboard_product_ident=Lower(Trim("product_ident")),
        )
        .values("dashboard_product_ident")
        .annotate(
            product_description=Max("product_description"),
            total_deliveries=Count("pk"),
            qc_passed=Count("pk", filter=Q(latest_job_status=JOB_OK)),
            qc_in_progress=Count(
                "pk",
                filter=Q(latest_job_status__in=IN_PROGRESS_STATUSES),
            ),
            needs_attention=Count("pk", filter=attention_status),
        )
        .filter(needs_attention__gt=0)
        .order_by(
            "-needs_attention",
            "-total_deliveries",
            "dashboard_product_ident",
        )[:limit]
    )
    return tuple(
        ProductAttention(
            identifier=row["dashboard_product_ident"] or "Not identified",
            description=row["product_description"] or "Product not identified",
            total_deliveries=row["total_deliveries"],
            qc_passed=row["qc_passed"],
            qc_in_progress=row["qc_in_progress"],
            needs_attention=row["needs_attention"],
        )
        for row in rows
    )


def _recent_activity(deliveries, *, account_access, limit):
    # Pull a small candidate set per source before merging it in memory. This
    # gives useful recent context without pretending to be a durable audit log.
    candidate_limit = max(limit * 2, limit)
    delivery_ids = deliveries.order_by().values("pk")
    jobs = (
        Job.objects.filter(delivery_id__in=Subquery(delivery_ids))
        .filter(
            Q(job_status__in=IN_PROGRESS_STATUSES)
            | Q(date_finished__isnull=False)
        )
        .select_related("delivery__user")
        .annotate(
            activity_at=Coalesce(
                "date_finished",
                "date_started",
                "date_created",
            )
        )
        .order_by("-activity_at", "-job_uuid")[:candidate_limit]
    )
    uploads = deliveries.select_related("user").order_by(
        "-date_uploaded",
        "-pk",
    )[:candidate_limit]
    submissions = (
        deliveries.filter(date_submitted__isnull=False)
        .select_related("user")
        .order_by("-date_submitted", "-pk")[:candidate_limit]
    )

    activity = []
    for job in jobs:
        activity.append(_job_activity(job, account_access))
    for delivery in uploads:
        activity.append(
            ActivityItem(
                kind="upload",
                tone="info",
                title="{} uploaded".format(delivery.filename),
                detail=_activity_detail(
                    delivery.product_description or "Delivery uploaded",
                    delivery.user.username,
                    account_access,
                ),
                occurred_at=delivery.date_uploaded,
            )
        )
    for delivery in submissions:
        activity.append(
            ActivityItem(
                kind="submission",
                tone="submitted",
                title="{} submitted to EEA".format(delivery.filename),
                detail=_activity_detail(
                    delivery.product_description or "Submission completed",
                    delivery.user.username,
                    account_access,
                ),
                occurred_at=delivery.date_submitted,
            )
        )

    activity.sort(key=lambda item: item.occurred_at, reverse=True)
    return tuple(activity[:limit])


def _job_activity(job, account_access):
    category = classify_job_status(job.job_status)
    if category == "passed":
        title = "{} passed QC".format(job.delivery.filename)
        tone = "success"
    elif category == "in_progress":
        title = "QC in progress for {}".format(job.delivery.filename)
        tone = "progress"
    elif category == "failed":
        title = "{} needs QC attention".format(job.delivery.filename)
        tone = "danger"
    elif category == "not_checked":
        title = "{} is ready for QC".format(job.delivery.filename)
        tone = "neutral"
    else:
        title = "QC status updated for {}".format(job.delivery.filename)
        tone = "neutral"
    return ActivityItem(
        kind="qc",
        tone=tone,
        title=title,
        detail=_activity_detail(
            job.product_description or job.product_ident or "QC job",
            job.delivery.user.username,
            account_access,
        ),
        occurred_at=job.activity_at,
    )


def _activity_detail(description, username, account_access):
    if account_access.can_view_other_users_deliveries:
        return "{} · {}".format(description, username)
    return description


def _percentage(part, total):
    if total <= 0:
        return 0.0
    return round((part / total) * 100.0, 4)


def _validate_limit(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 20:
        raise ValueError("Dashboard item limits must be integers from 1 to 20.")
