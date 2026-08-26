"""Persisted QC job history and provenance."""

from uuid import uuid4

from django.conf import settings
from django.db import models
from django.utils import timezone

from qc_tool.aoi import AOI_CODE_MAX_LENGTH
from qc_tool.common import JOB_WAITING


class Job(models.Model):
    job_uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    delivery = models.ForeignKey(
        "dashboard.Delivery",
        on_delete=models.CASCADE,
    )
    date_created = models.DateTimeField(default=timezone.now)
    date_started = models.DateTimeField(blank=True, null=True)
    date_finished = models.DateTimeField(blank=True, null=True)
    job_status = models.CharField(max_length=64, default=JOB_WAITING)
    product_ident = models.CharField(max_length=64)
    product_description = models.CharField(max_length=500)
    aoi_code = models.CharField(
        max_length=AOI_CODE_MAX_LENGTH,
        default=None,
        blank=True,
        null=True,
        editable=False,
        help_text="Canonical AOI code reported by the delivery job result.",
    )
    aoi_code_submitted = models.CharField(
        max_length=AOI_CODE_MAX_LENGTH,
        default=None,
        blank=True,
        null=True,
        editable=False,
        help_text="Canonical AOI code verified from the submitted ZIP.",
    )
    skip_steps = models.CharField(
        max_length=100,
        default=None,
        blank=True,
        null=True,
    )
    worker_url = models.CharField(
        max_length=500,
        default=None,
        blank=True,
        null=True,
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="requested_qc_jobs",
    )
    requested_by_username = models.CharField(max_length=150, blank=True)
    request_source = models.CharField(max_length=16, default="legacy")
    requested_api_token_id = models.PositiveBigIntegerField(
        blank=True,
        null=True,
        editable=False,
        help_text=(
            "Identifier snapshot of the personal API token used to request "
            "the job. It intentionally has no foreign key so deleting a "
            "credential cannot rewrite audit history."
        ),
    )
    requested_api_token_name = models.CharField(max_length=80, blank=True)
    product_release = models.ForeignKey(
        "dashboard.ProductRelease",
        blank=True,
        null=True,
        on_delete=models.PROTECT,
        related_name="jobs",
    )
    qc_definition = models.ForeignKey(
        "dashboard.QcDefinition",
        blank=True,
        null=True,
        on_delete=models.PROTECT,
        related_name="jobs",
    )
    input_sha256 = models.CharField(max_length=64, blank=True, editable=False)
    reference_period = models.CharField(
        max_length=32,
        blank=True,
        editable=False,
    )
    qc_tool_version = models.CharField(
        max_length=128,
        blank=True,
        editable=False,
    )
    result_metadata = models.JSONField(blank=True, null=True, editable=False)
    result_sha256 = models.CharField(max_length=64, blank=True, editable=False)
    result_received_at = models.DateTimeField(
        blank=True,
        null=True,
        editable=False,
    )

    class Meta:
        app_label = "dashboard"
        indexes = (
            models.Index(fields=("aoi_code",), name="dash_job_aoi_idx"),
            models.Index(
                fields=("aoi_code_submitted",),
                name="dash_job_zip_aoi_idx",
            ),
            models.Index(
                fields=("delivery", "-date_created", "-job_uuid"),
                name="dash_job_latest_idx",
            ),
            models.Index(
                fields=("job_status", "date_created"),
                name="dash_job_queue_idx",
            ),
        )

    def __str__(self):
        return "{0} | {1} | {2}".format(
            str(self.job_uuid),
            self.delivery.filename,
            self.job_status,
        )

    def apply_result_metadata(self, job_result):
        from qc_tool.frontend.dashboard.services.aoi import apply_result_aoi

        return apply_result_aoi(self, job_result)

    def update_status(self, job_status):
        from qc_tool.frontend.dashboard.services.aoi import update_job_status

        update_job_status(self, job_status)
