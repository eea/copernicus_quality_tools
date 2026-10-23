"""A receipt commits with imported rows, closing the filesystem/SQL crash gap."""

from django.conf import settings
from django.db import models
from django.utils import timezone


class TransferReceipt(models.Model):
    package_id = models.UUIDField(unique=True, editable=False)
    package_sha256 = models.CharField(max_length=64, editable=False)
    operation_id = models.UUIDField(unique=True, editable=False)
    plan_sha256 = models.CharField(max_length=64, editable=False)
    profile = models.CharField(max_length=24, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                              related_name="+", editable=False)
    actor_name = models.CharField(max_length=150, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    summary = models.JSONField(default=dict, editable=False)

    class Meta:
        db_table = "qc_database_transfer_receipt"
