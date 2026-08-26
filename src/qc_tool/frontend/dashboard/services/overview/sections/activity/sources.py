"""Bounded database sources used to derive recent dashboard activity."""

from django.db.models import Q
from django.db.models import Subquery
from django.db.models.functions import Coalesce

from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.dashboard.services.deliveries.summary import (
    IN_PROGRESS_STATUSES,
)


def recent_activity_sources(deliveries, *, limit):
    """Return three lazily evaluated, bounded activity querysets."""

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
    return jobs, uploads, submissions
