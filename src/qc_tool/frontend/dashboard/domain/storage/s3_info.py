"""Remote delivery coordinates and an opaque reference to external credentials."""

from django.db import models


class S3Info(models.Model):
    host = models.CharField(max_length=200)
    credential_ref = models.CharField(
        max_length=32,
        blank=True,
        editable=False,
        help_text="Reference to private S3 credentials outside the database; blank for imported history.",
    )
    bucketname = models.CharField(max_length=100)
    key_prefix = models.CharField(max_length=500)

    class Meta:
        app_label = "dashboard"
        db_table = "storage_delivery_source"
