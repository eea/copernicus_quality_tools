"""Persisted QC job history and provenance."""

from uuid import uuid4

from django.conf import settings
from django.db import models
from django.utils import timezone

from qc_tool.product_units import PRODUCT_UNIT_CODE_MAX_LENGTH
from qc_tool.common import JOB_WAITING


class Job(models.Model):
    class RequestSource(models.TextChoices):
        BROWSER = "browser", "Browser"
        API = "api", "API"

    job_uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    delivery = models.ForeignKey(
        "dashboard.Delivery",
        on_delete=models.CASCADE,
        db_index=False,  # Covered by execution_job_latest_idx.
    )
    date_created = models.DateTimeField(default=timezone.now)
    date_started = models.DateTimeField(blank=True, null=True)
    date_finished = models.DateTimeField(blank=True, null=True)
    job_status = models.CharField(max_length=64, default=JOB_WAITING)
    product_ident = models.CharField(max_length=64)
    product_description = models.CharField(max_length=500)
    product_unit_code = models.CharField(
        max_length=PRODUCT_UNIT_CODE_MAX_LENGTH,
        default=None,
        blank=True,
        null=True,
        editable=False,
        help_text="Canonical product unit code reported by the delivery job result.",
    )
    verified_product_unit_code = models.CharField(
        max_length=PRODUCT_UNIT_CODE_MAX_LENGTH,
        default=None,
        blank=True,
        null=True,
        editable=False,
        help_text="Canonical product unit code verified from this job's input ZIP; not a review decision.",
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
    request_source = models.CharField(
        max_length=16,
        choices=RequestSource.choices,
        blank=True,
        null=True,
        default=None,
        help_text="Request channel when known; NULL means the channel was not recorded.",
    )
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

    class Meta:
        app_label = "dashboard"
        db_table = "execution_job"
        constraints = (
            models.CheckConstraint(
                condition=(
                    models.Q(request_source__isnull=True)
                    | models.Q(request_source__in=("browser", "api"))
                ),
                name="execution_job_source_valid",
            ),
        )
        indexes = (
            models.Index(fields=("product_unit_code",), name="execution_job_unit_idx"),
            models.Index(
                fields=("verified_product_unit_code",),
                name="execution_job_zip_unit_idx",
            ),
            models.Index(
                fields=("delivery", "-date_created", "-job_uuid"),
                name="execution_job_latest_idx",
            ),
            models.Index(
                fields=("job_status", "date_created"),
                name="execution_job_queue_idx",
            ),
        )

    def __str__(self):
        return "{0} | {1} | {2}".format(
            str(self.job_uuid),
            self.delivery.filename,
            self.job_status,
        )

    def update_status(self, job_status):
        from qc_tool.frontend.dashboard.services.product_units import update_job_status

        update_job_status(self, job_status)
