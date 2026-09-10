"""Current product-manager decision for duplicate AOI submissions."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .delivery_submission import DeliverySubmission


class SubmissionConflict(models.Model):
    """Current manager decision for competing submissions of one expected AOI."""

    class State(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"
        DISMISSED = "dismissed", "Closed"

    product_aoi = models.OneToOneField(
        "dashboard.ProductAOI",
        on_delete=models.PROTECT,
        related_name="submission_conflict",
    )
    state = models.CharField(
        max_length=10,
        choices=State.choices,
        default=State.OPEN,
    )
    version = models.PositiveIntegerField(default=1)
    selected_submission = models.ForeignKey(
        DeliverySubmission,
        blank=True,
        null=True,
        on_delete=models.PROTECT,
        related_name="selected_for_conflicts",
    )
    opened_at = models.DateTimeField()
    resolved_at = models.DateTimeField(blank=True, null=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="resolved_submission_conflicts",
    )
    resolved_by_username = models.CharField(max_length=150, blank=True)
    resolution_notes = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "dashboard"
        db_table = "publication_conflict"
        ordering = ("state", "-opened_at", "pk")
        constraints = (
            models.CheckConstraint(
                condition=models.Q(version__gt=0),
                name="pub_conflict_version_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        state="open",
                        selected_submission__isnull=True,
                        resolved_at__isnull=True,
                    )
                    | models.Q(
                        state="resolved",
                        selected_submission__isnull=False,
                        resolved_at__isnull=False,
                    )
                    | models.Q(
                        state="dismissed",
                        selected_submission__isnull=True,
                        resolved_at__isnull=False,
                    )
                ),
                name="pub_conflict_state_consistent",
            ),
        )

    def clean(self):
        super().clean()
        selected = self.selected_submission
        if selected is None:
            return
        if selected.product_aoi_id != self.product_aoi_id:
            raise ValidationError(
                {"selected_submission": "Select a submission for this AOI."}
            )
        if selected.publication_state != DeliverySubmission.PublicationState.PUBLISHED:
            raise ValidationError(
                {"selected_submission": "Only a published submission can be selected."}
            )

    def __str__(self):
        return "{} ({})".format(self.product_aoi, self.state)
