"""Find visible products whose latest QC states need attention."""

from django.db.models import Count
from django.db.models import Max
from django.db.models import Q
from django.db.models.functions import Lower
from django.db.models.functions import Trim

from qc_tool.common import JOB_OK
from qc_tool.frontend.dashboard.services.deliveries import (
    with_latest_job_status,
)
from qc_tool.frontend.dashboard.services.deliveries.summary import (
    FAILED_STATUSES,
)
from qc_tool.frontend.dashboard.services.deliveries.summary import (
    FILE_NOT_FOUND_STATUS,
)
from qc_tool.frontend.dashboard.services.deliveries.summary import (
    IN_PROGRESS_STATUSES,
)

from ..contracts import ProductAttention


def build_product_attention(deliveries, limit):
    """Return bounded, case-normalized product aggregates needing action."""

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
