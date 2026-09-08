"""Immutable executable QC-definition snapshots."""

from django.core.exceptions import ValidationError
from django.db import models


class QcDefinition(models.Model):
    """One immutable revision of an executable product-definition document."""

    product_ident = models.CharField(max_length=64)
    digest = models.CharField(max_length=64)
    description = models.CharField(max_length=500)
    document = models.JSONField()
    source_path = models.CharField(max_length=500)
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "dashboard"
        db_table = "catalog_definition_revision"
        ordering = ("product_ident", "-imported_at", "-pk")
        constraints = (
            models.CheckConstraint(
                condition=~models.Q(product_ident=""),
                name="catalog_def_ident_present",
            ),
            models.CheckConstraint(
                condition=~models.Q(digest=""),
                name="catalog_def_digest_present",
            ),
            models.UniqueConstraint(
                fields=("product_ident", "digest"),
                name="catalog_def_ident_digest_uniq",
            ),
        )
        indexes = (
            models.Index(
                fields=("product_ident", "-imported_at"),
                name="catalog_def_ident_date_idx",
            ),
        )

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exclude(
            product_ident=self.product_ident,
            digest=self.digest,
            description=self.description,
            document=self.document,
            source_path=self.source_path,
        ).exists():
            raise ValidationError(
                "QC definition revisions are immutable; import a new revision."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("QC definition revisions cannot be deleted.")

    def __str__(self):
        return "{} @ {}".format(self.product_ident, self.digest[:12])
