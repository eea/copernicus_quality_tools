"""Uploaded ZIP delivery record and its compatibility helpers."""

from django.conf import settings
from django.db import models
from django.utils import timezone

from qc_tool.aoi import AOI_CODE_MAX_LENGTH
from qc_tool.common import JOB_OK


class Delivery(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.CASCADE,
    )
    filename = models.CharField(max_length=500)
    size_bytes = models.BigIntegerField()
    date_uploaded = models.DateTimeField(default=timezone.now)
    date_submitted = models.DateTimeField(blank=True, null=True)
    product_ident = models.CharField(
        max_length=64,
        default=None,
        blank=True,
        null=True,
    )
    product_description = models.CharField(
        max_length=500,
        default=None,
        blank=True,
        null=True,
    )
    aoi_code = models.CharField(
        max_length=AOI_CODE_MAX_LENGTH,
        default=None,
        blank=True,
        null=True,
        editable=False,
        help_text="Canonical AOI code projected from the latest delivery job.",
    )
    aoi_code_submitted = models.CharField(
        max_length=AOI_CODE_MAX_LENGTH,
        default=None,
        blank=True,
        null=True,
        editable=False,
        help_text=(
            "Canonical AOI code verified from the ZIP by the latest QC job. "
            "ProductAOI.aoi_code is the authoritative expected value."
        ),
    )
    content_sha256 = models.CharField(
        max_length=64,
        default=None,
        blank=True,
        null=True,
        editable=False,
    )
    is_deleted = models.BooleanField(default=False)
    s3 = models.ForeignKey(
        "dashboard.S3Info",
        null=True,
        on_delete=models.CASCADE,
    )

    class Meta:
        app_label = "dashboard"
        db_table = "execution_delivery"
        verbose_name = "Delivery"
        verbose_name_plural = "Deliveries"
        indexes = (
            models.Index(fields=("aoi_code",), name="execution_delivery_aoi_idx"),
            models.Index(
                fields=("aoi_code_submitted",),
                name="execution_delivery_zip_aoi_idx",
            ),
            models.Index(
                fields=("content_sha256",),
                name="execution_delivery_sha_idx",
            ),
        )

    def __str__(self):
        return "User: {:s} | File: {:s}".format(
            self.user.username,
            self.filename,
        )

    def create_job(
        self,
        product_ident,
        skip_steps,
        *,
        requested_by=None,
        request_source="legacy",
        api_token=None,
        account_access=None,
    ):
        # Import through the compatibility boundary so existing integrations
        # can still replace product-description lookup in dashboard.models.
        import qc_tool.frontend.dashboard.models as dashboard_models
        from qc_tool.frontend.dashboard.services.aoi import create_delivery_job

        job = create_delivery_job(
            self,
            product_ident=product_ident,
            product_description=dashboard_models.find_product_description(
                product_ident
            ),
            skip_steps=skip_steps,
            requested_by=requested_by,
            request_source=request_source,
            api_token=api_token,
            account_access=account_access,
        )
        return str(job.job_uuid).lower().replace("-", "")

    def sync_from_latest_job(self):
        from qc_tool.frontend.dashboard.services.aoi import (
            refresh_delivery_projection,
        )

        return refresh_delivery_projection(self)

    def get_submittable_job(self):
        """Return only the deterministic latest successful job."""

        if self.is_deleted or self.date_submitted is not None:
            return None
        Job = self._meta.apps.get_model("dashboard", "Job")
        latest_job = (
            Job.objects.filter(delivery_id=self.id)
            .order_by("-date_created", "-job_uuid")
            .first()
        )
        if latest_job is None or latest_job.job_status != JOB_OK:
            return None
        return latest_job

    def is_submitted(self):
        return self.date_submitted is not None
