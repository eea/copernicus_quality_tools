"""Retained manager decisions, separate from immutable publication receipts."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .retention import ConflictEventQuerySet


class SubmissionReviewEvent(models.Model):
    """Append-only approval or decline with its account and reason snapshots."""

    objects = ConflictEventQuerySet.as_manager()

    class Decision(models.TextChoices):
        APPROVED = "approved", "Approved"
        DECLINED = "declined", "Declined"

    submission = models.ForeignKey(
        "dashboard.DeliverySubmission", on_delete=models.PROTECT,
        related_name="review_events",
    )
    version = models.PositiveIntegerField()
    decision = models.CharField(max_length=10, choices=Decision.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, blank=True, null=True,
        on_delete=models.SET_NULL, related_name="submission_review_events",
    )
    actor_username = models.CharField(max_length=150)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "dashboard"
        db_table = "publication_review_event"
        base_manager_name = "objects"
        ordering = ("created_at", "pk")
        constraints = (
            models.UniqueConstraint(
                fields=("submission", "version"),
                name="pub_review_event_version_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gt=0),
                name="pub_review_version_positive",
            ),
        )

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Submission review events are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Submission review events are append-only.")
