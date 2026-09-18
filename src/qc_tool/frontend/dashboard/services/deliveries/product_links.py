"""Authorized catalog destinations shared by delivery lists and details."""

from django.urls import reverse

from qc_tool.frontend.dashboard.models import DeliverySubmission, Job, Product
from qc_tool.product_security import normalize_product_ident


def add_delivery_product_links(rows, account_access):
    """Resolve catalog destinations with at most three page-level lookups.

    Rows must already be authorized, with submission IDs limited to receipts
    visible to the viewer. A delivery's recorded product identifier names its
    QC recipe. Several catalog products can use that recipe, so only the
    visible submission or selected QC run can establish its parent product.
    Unvalidated rows may link to an exact identity, never an inferred parent.
    """

    job_ids = {row["last_job_uuid"] for row in rows if row["last_job_uuid"]}
    submission_ids = {row["submission_id"] for row in rows if row.get("submission_id")}
    job_products = {
        str(job_id): product_ident
        for job_id, product_ident in Job.objects.filter(
            job_uuid__in=job_ids, product_release__isnull=False,
        ).values_list("job_uuid", "product_release__product__ident")
    }
    submission_products = {
        str(submission_id): product_ident
        for submission_id, product_ident in DeliverySubmission.objects.filter(
            submission_uuid__in=submission_ids,
        ).values_list("submission_uuid", "product_release__product__ident")
    }
    candidates = [
        submission_products.get(str(row.get("submission_id")))
        or job_products.get(str(row["last_job_uuid"]))
        or normalize_product_ident(row.get("product_ident"))
        for row in rows
    ]
    # Product details require a current release, including for removed products.
    # Preserve that page's access boundary even for a viewer's own delivery.
    allowed = {
        ident for ident in candidates
        if ident is not None and account_access.can_browse_product(ident)
    }
    products = dict(Product.objects.filter(
        ident__in=allowed, releases__is_current=True,
    ).values_list("ident", "name").distinct())
    for row, ident in zip(rows, candidates):
        name = products.get(ident)
        row["product_url"] = reverse("product_detail", args=(ident,)) if name else ""
        row["product_display_name"] = name or ""
