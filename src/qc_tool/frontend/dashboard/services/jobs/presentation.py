"""Read-only delivery context for QC history pages."""

from django.template.defaultfilters import filesizeformat
from django.urls import reverse

from qc_tool.frontend.dashboard.access import can_manage_delivery
from qc_tool.frontend.dashboard.models import DeliverySubmission, Job
from qc_tool.frontend.dashboard.services.deliveries.listing.statuses import (
    classify_delivery_status,
    delivery_status_presentation,
)
from qc_tool.frontend.dashboard.services.deliveries.product_links import (
    add_delivery_product_links,
)
from qc_tool.frontend.dashboard.services.submissions.access import visible_submissions


def job_history_delivery_summary(delivery, account_access):
    """Describe an authorized delivery using the shared entity-summary shape.

    Receipt visibility and catalog links follow the same boundaries as the
    deliveries list. The history endpoint refreshes this summary alongside
    its job rows, keeping processing and review states current.
    """

    latest_job = (
        Job.objects.filter(delivery_id=delivery.pk)
        .order_by("-date_created", "-job_uuid")
        .values("job_uuid", "job_status")
        .first()
    )
    submission = (
        visible_submissions(account_access)
        .filter(delivery_id=delivery.pk)
        .values("submission_uuid", "review_state", "publication_state")
        .first()
    ) or {}
    job_status = latest_job["job_status"] if latest_job else None
    status = classify_delivery_status(
        job_status, delivery.date_submitted,
        submission.get("review_state"), submission.get("publication_state"),
    )
    row = {
        "product_ident": delivery.product_ident,
        "last_job_uuid": latest_job["job_uuid"] if latest_job else None,
        "submission_id": submission.get("submission_uuid"),
    }
    add_delivery_product_links([row], account_access)
    facts = [{"label": "Size", "value": filesizeformat(delivery.size_bytes)}]
    if delivery.date_uploaded:
        facts.append({"label": "Uploaded", "datetime": delivery.date_uploaded})
    if delivery.product_unit_code:
        facts.append({"label": "Reported product unit", "value": delivery.product_unit_code})
    return {
        "kind": "Delivery",
        "reference": f"#{delivery.pk}",
        "title": delivery.filename,
        "icon": "file",
        "description": (
            row["product_display_name"]
            or delivery.product_description
            or "Product not identified"
        ),
        "description_label": "Product",
        "description_url": row["product_url"],
        "status_label": "Delivery status",
        "status": delivery_status_presentation(status, job_status),
        "action": _first_qc_action(delivery, account_access, latest_job),
        "facts": facts,
    }


def _first_qc_action(delivery, account_access, latest_job):
    """Offer setup only while the owner can start the delivery's first run."""

    if (
        latest_job is not None
        or delivery.is_deleted
        or delivery.date_submitted is not None
        or not account_access.can_run_qc
        or not can_manage_delivery(account_access, delivery)
        # A receipt also reserves a delivery before publication completes.
        # Its visibility must not weaken the start-job restriction.
        or DeliverySubmission.objects.filter(delivery_id=delivery.pk).exists()
    ):
        return None
    return {
        "label": "Run QC",
        "url": f"{reverse('setup_job')}?deliveries={delivery.pk}",
        "icon": "play",
    }
