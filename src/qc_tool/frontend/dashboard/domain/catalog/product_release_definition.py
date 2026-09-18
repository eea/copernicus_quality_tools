"""Explicit release-to-QC-definition mappings."""

from django.core.exceptions import ValidationError
from django.db import models

from .product_release import ProductRelease
from .qc_definition import QcDefinition


class ProductReleaseDefinition(models.Model):
    """Explicit mapping; product-definition filenames are never grouped by guess."""

    product_release = models.ForeignKey(
        ProductRelease,
        on_delete=models.PROTECT,
        related_name="definition_links",
        db_index=False,  # Covered by catalog_release_def_uniq.
    )
    qc_definition = models.ForeignKey(
        QcDefinition,
        on_delete=models.PROTECT,
        related_name="release_links",
    )
    is_primary = models.BooleanField(default=False)

    class Meta:
        app_label = "dashboard"
        db_table = "catalog_release_definition"
        ordering = ("product_release_id", "-is_primary", "pk")
        constraints = (
            models.UniqueConstraint(
                fields=("product_release", "qc_definition"),
                name="catalog_release_def_uniq",
            ),
            models.UniqueConstraint(
                fields=("product_release",),
                condition=models.Q(is_primary=True),
                name="catalog_release_primary_uniq",
            ),
        )

    def __str__(self):
        return "{} -> {}".format(self.product_release, self.qc_definition)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exclude(
            product_release_id=self.product_release_id,
            qc_definition_id=self.qc_definition_id,
            is_primary=self.is_primary,
        ).exists():
            raise ValidationError(
                "Release-definition links are immutable with their release."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Release-definition links are historical records.")
