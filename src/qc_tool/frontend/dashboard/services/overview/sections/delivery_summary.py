"""Aggregate delivery and latest-QC counts for the overview KPIs."""

from collections import defaultdict
from datetime import timedelta

from django.db.models import BooleanField
from django.db.models import Case
from django.db.models import Count
from django.db.models import Value
from django.db.models import When
from django.utils import timezone

from qc_tool.frontend.dashboard.services.deliveries import classify_job_status
from qc_tool.frontend.dashboard.services.deliveries import (
    with_latest_job_status,
)

from ..contracts import DeliveryOverview


def build_delivery_overview(deliveries):
    """Return all delivery KPI counts with one grouped database query."""

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
