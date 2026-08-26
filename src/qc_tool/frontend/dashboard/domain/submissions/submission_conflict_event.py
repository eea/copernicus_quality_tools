"""Append-only duplicate-AOI decision history."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .delivery_submission import DeliverySubmission
from .submission_conflict import SubmissionConflict


class SubmissionConflictEvent(models.Model):
    """Append-only audit trail for conflict opening, reopening, and resolution."""

    class EventType(models.TextChoices):
        OPENED = "opened", "Opened"
        REOPENED = "reopened", "Reopened"
        RESOLVED = "resolved", "Resolved"

    conflict = models.ForeignKey(
        SubmissionConflict,
        on_delete=models.PROTECT,
        related_name="events",
    )
    version = models.PositiveIntegerField()
    event_type = models.CharField(max_length=10, choices=EventType.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="submission_conflict_events",
    )
    actor_username = models.CharField(max_length=150, blank=True)
    selected_submission = models.ForeignKey(
        DeliverySubmission,
        blank=True,
        null=True,
        on_delete=models.PROTECT,
        related_name="conflict_events",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "dashboard"
        ordering = ("conflict_id", "version", "created_at", "pk")
        constraints = (
            models.UniqueConstraint(
                fields=("conflict", "version", "event_type"),
                name="dash_conflict_event_version_uniq",
            ),
        )

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Conflict events are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Conflict events are append-only.")

    def __str__(self):
        return "{} v{} {}".format(
            self.conflict_id,
            self.version,
            self.event_type,
        )
