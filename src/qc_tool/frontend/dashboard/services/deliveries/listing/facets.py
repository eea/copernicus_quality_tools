"""Access-scoped facet counts for the server-backed delivery list."""

from django.db.models import Count
from django.db.models import Q

from qc_tool.common import JOB_OK
from qc_tool.common import JOB_RUNNING
from qc_tool.common import JOB_WAITING
from qc_tool.frontend.dashboard.access.delivery_querysets import (
    visible_deliveries,
)
from qc_tool.frontend.dashboard.services.deliveries.summary import (
    with_latest_job_status,
)
from qc_tool.frontend.dashboard.services.submissions.access import visible_submissions

from .statuses import DeliveryStatusCounts


def count_delivery_statuses(
    account_access,
    *,
    search="",
    product_description=None,
    aoi_code=None,
):
    """Count each visible Delivery once before applying the active status."""

    queryset = with_latest_job_status(visible_deliveries(account_access))
    if search:
        queryset = queryset.filter(filename__contains=search)
    if product_description is not None:
        queryset = queryset.filter(product_description=product_description)
    if aoi_code is not None:
        queryset = queryset.filter(aoi_code__contains=aoi_code)

    needs_correction = Q(
        submission__in=visible_submissions(account_access).filter(
            publication_state="published", review_state="rejected",
        ),
    )
    accepted = Q(
        submission__in=visible_submissions(account_access).filter(
            publication_state="published", review_state="accepted",
        ),
    )
    unsubmitted = Q(date_submitted__isnull=True) & ~needs_correction & ~accepted
    non_failure_statuses = (JOB_WAITING, JOB_RUNNING, JOB_OK)
    counts = queryset.aggregate(
        all=Count("pk"),
        submitted=Count(
            "pk", filter=Q(date_submitted__isnull=False) & ~needs_correction & ~accepted,
        ),
        accepted=Count("pk", filter=accepted),
        needs_correction=Count("pk", filter=needs_correction),
        not_validated=Count(
            "pk",
            filter=unsubmitted & Q(latest_job_status__isnull=True),
        ),
        running=Count(
            "pk",
            filter=unsubmitted
            & Q(latest_job_status__in=(JOB_WAITING, JOB_RUNNING)),
        ),
        passed=Count(
            "pk",
            filter=unsubmitted & Q(latest_job_status=JOB_OK),
        ),
        failed=Count(
            "pk",
            filter=unsubmitted
            & Q(latest_job_status__isnull=False)
            & ~Q(latest_job_status__in=non_failure_statuses),
        ),
    )
    return DeliveryStatusCounts(**counts)
