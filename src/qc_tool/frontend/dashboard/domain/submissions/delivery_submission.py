"""Durable publication record for a QC-approved delivery."""

from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db import router
from django.db import transaction

from qc_tool.aoi import AOI_CODE_MAX_LENGTH

from .retention import SubmissionQuerySet


class DeliverySubmission(models.Model):
    """Immutable association between an upload, its successful job, and AOI."""

    objects = SubmissionQuerySet.as_manager()

    class PublicationState(models.TextChoices):
        PENDING = "pending", "Pending"
        PUBLISHING = "publishing", "Publishing"
        PUBLISHED = "published", "Published"
        FAILED = "failed", "Failed"

    class ReviewState(models.TextChoices):
        ACCEPTED = "accepted", "Accepted"
        CONFLICT = "conflict", "Conflict"
        REJECTED = "rejected", "Rejected"

    class RequestChannel(models.TextChoices):
        BROWSER = "browser", "Browser"
        API = "api", "API"
        LEGACY = "legacy", "Legacy backfill"

    submission_uuid = models.UUIDField(
        primary_key=True,
        default=uuid4,
        editable=False,
    )
    delivery = models.OneToOneField(
        "dashboard.Delivery",
        on_delete=models.PROTECT,
        related_name="submission",
    )
    job = models.OneToOneField(
        "dashboard.Job",
        on_delete=models.PROTECT,
        related_name="submission",
    )
    product_release = models.ForeignKey(
        "dashboard.ProductRelease",
        on_delete=models.PROTECT,
        related_name="submissions",
    )
    product_aoi = models.ForeignKey(
        "dashboard.ProductAOI",
        on_delete=models.PROTECT,
        related_name="submissions",
    )
    aoi_code = models.CharField(max_length=AOI_CODE_MAX_LENGTH, editable=False)
    aoi_code_submitted = models.CharField(
        max_length=AOI_CODE_MAX_LENGTH,
        editable=False,
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="delivery_submissions",
    )
    submitted_by_username = models.CharField(max_length=150)
    request_channel = models.CharField(
        max_length=10,
        choices=RequestChannel.choices,
    )
    api_token_id = models.PositiveBigIntegerField(
        blank=True,
        null=True,
        editable=False,
        help_text=(
            "Identifier snapshot of the API token used for submission. "
            "It is deliberately not a foreign key because credentials may "
            "be deleted while submission provenance must remain immutable."
        ),
    )
    api_token_name = models.CharField(max_length=80, blank=True)
    publication_state = models.CharField(
        max_length=12,
        choices=PublicationState.choices,
        default=PublicationState.PENDING,
    )
    review_state = models.CharField(
        max_length=10,
        choices=ReviewState.choices,
        default=ReviewState.ACCEPTED,
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    publication_claimed_at = models.DateTimeField(blank=True, null=True)
    publication_token = models.UUIDField(blank=True, null=True, editable=False)
    published_at = models.DateTimeField(blank=True, null=True)
    artifact_path = models.CharField(max_length=1000, blank=True)
    artifact_digest = models.CharField(max_length=64, blank=True)
    input_digest = models.CharField(max_length=64, blank=True)
    failure_code = models.CharField(max_length=64, blank=True)
    failure_message = models.CharField(max_length=500, blank=True)

    class Meta:
        app_label = "dashboard"
        db_table = "publication_submission"
        base_manager_name = "objects"
        ordering = ("-requested_at", "submission_uuid")
        constraints = (
            models.CheckConstraint(
                condition=~models.Q(aoi_code=""),
                name="pub_submission_aoi_not_empty",
            ),
            models.CheckConstraint(
                condition=~models.Q(aoi_code_submitted=""),
                name="pub_submission_zip_aoi_present",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(publication_state="published")
                    | (
                        models.Q(published_at__isnull=False)
                        & ~models.Q(artifact_path="")
                        & ~models.Q(artifact_digest="")
                        & ~models.Q(input_digest="")
                    )
                ),
                name="pub_submission_complete",
            ),
        )
        indexes = (
            models.Index(
                fields=("product_aoi", "publication_state", "review_state"),
                name="pub_submission_aoi_state_idx",
            ),
            models.Index(
                fields=("product_release", "publication_state"),
                name="pub_submission_release_idx",
            ),
        )

    def clean(self):
        super().clean()
        if not self.product_aoi_id:
            return
        expected_release_id = self.product_aoi.product_release_id
        if self.product_release_id != expected_release_id:
            raise ValidationError(
                {"product_aoi": "The AOI does not belong to this product release."}
            )
        if self.aoi_code != self.product_aoi.aoi_code:
            raise ValidationError(
                {"aoi_code": "Expected AOI snapshot differs from the catalog."}
            )

    def save(self, *args, **kwargs):
        database = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=database):
            previous = (
                type(self).objects.using(database)
                .select_for_update()
                .filter(pk=self.pk)
                .first()
            )
            if previous is not None:
                self._require_retained_history(previous)
            return super().save(*args, **kwargs)

    def _require_retained_history(self, previous):
        identity = dict(
            delivery_id=self.delivery_id,
            job_id=self.job_id,
            product_release_id=self.product_release_id,
            product_aoi_id=self.product_aoi_id,
            aoi_code=self.aoi_code,
            aoi_code_submitted=self.aoi_code_submitted,
            submitted_by_id=self.submitted_by_id,
            submitted_by_username=self.submitted_by_username,
            request_channel=self.request_channel,
            api_token_id=self.api_token_id,
            api_token_name=self.api_token_name,
            requested_at=self.requested_at,
            input_digest=self.input_digest,
        )
        if any(getattr(previous, field) != value for field, value in identity.items()):
            raise ValidationError("Submission identity and provenance are immutable.")
        if previous.publication_state == self.PublicationState.PUBLISHED:
            mutable_fields = {"review_state"}
            if any(
                getattr(previous, field.attname) != getattr(self, field.attname)
                for field in self._meta.concrete_fields
                if field.attname not in mutable_fields
            ):
                raise ValidationError("Published submission receipts are immutable.")

    def delete(self, *args, **kwargs):
        raise ValidationError("Delivery submissions are retained as audit history.")

    def __str__(self):
        return "{} / {} / {}".format(
            self.product_release.release_key,
            self.aoi_code,
            self.submission_uuid,
        )
