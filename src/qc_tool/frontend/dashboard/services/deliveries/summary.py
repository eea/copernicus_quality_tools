"""Small, read-only aggregates for the deliveries workspace."""

from dataclasses import dataclass

from django.db.models import Count
from django.db.models import OuterRef
from django.db.models import Subquery

from qc_tool.common import JOB_ERROR
from qc_tool.common import JOB_FAILED
from qc_tool.common import JOB_LOST
from qc_tool.common import JOB_OK
from qc_tool.common import JOB_PARTIAL
from qc_tool.common import JOB_RUNNING
from qc_tool.common import JOB_TIMEOUT
from qc_tool.common import JOB_WAITING
from qc_tool.frontend.dashboard.access.delivery_querysets import visible_deliveries
from qc_tool.frontend.dashboard.models import Job


IN_PROGRESS_STATUSES = (JOB_WAITING, JOB_RUNNING)
FAILED_STATUSES = (JOB_PARTIAL, JOB_FAILED, JOB_ERROR, JOB_TIMEOUT, JOB_LOST)
FILE_NOT_FOUND_STATUS = "file_not_found"


def with_latest_job_status(queryset):
    """Annotate deliveries with their deterministically latest job status.

    Keeping this annotation in one place prevents the delivery list summary and
    the dashboard from developing subtly different definitions of "latest".
    """

    latest_status = (
        Job.objects.filter(delivery_id=OuterRef("pk"))
        .order_by("-date_created", "-job_uuid")
        .values("job_status")[:1]
    )
    return queryset.annotate(latest_job_status=Subquery(latest_status))


def classify_job_status(status):
    """Map a stored job status to the stable delivery-summary vocabulary."""

    if status == JOB_OK:
        return "passed"
    if status in IN_PROGRESS_STATUSES:
        return "in_progress"
    if status in FAILED_STATUSES or status == FILE_NOT_FOUND_STATUS:
        return "failed"
    if status is None:
        return "not_checked"
    return "other"


@dataclass(frozen=True)
class DeliverySummary:
    """Counts shown above the delivery table for one effective access scope."""

    total: int
    passed: int
    in_progress: int
    failed: int
    not_checked: int
    other: int

    def as_dict(self):
        """Return the stable JSON contract consumed by the workspace UI."""

        return {
            "total": self.total,
            "passed": self.passed,
            "in_progress": self.in_progress,
            "failed": self.failed,
            "not_checked": self.not_checked,
            "other": self.other,
        }


def summarize_deliveries(account_access):
    """Aggregate each delivery by its latest job, within the visible scope."""

    status_counts = (
        with_latest_job_status(visible_deliveries(account_access))
        .values("latest_job_status")
        .annotate(count=Count("pk"))
    )
    total = passed = in_progress = failed = not_checked = other = 0
    for row in status_counts:
        count = row["count"]
        category = classify_job_status(row["latest_job_status"])
        total += count
        if category == "passed":
            passed += count
        elif category == "in_progress":
            in_progress += count
        elif category == "failed":
            failed += count
        elif category == "not_checked":
            not_checked += count
        else:
            other += count

    return DeliverySummary(
        total=total,
        passed=passed,
        in_progress=in_progress,
        failed=failed,
        not_checked=not_checked,
        other=other,
    )
