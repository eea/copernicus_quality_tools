"""Expected AOIs belonging to a product release."""

from django.core.exceptions import ValidationError
from django.db import models

from qc_tool.aoi import AOI_CODE_MAX_LENGTH
from qc_tool.aoi import normalize_aoi_code

from .product_release import ProductRelease


class ProductAOI(models.Model):
    """One immutable, authoritative expected part of a release."""

    product_release = models.ForeignKey(
        ProductRelease,
        on_delete=models.PROTECT,
        related_name="aois",
    )
    aoi_code = models.CharField(max_length=AOI_CODE_MAX_LENGTH)
    source_value = models.CharField(max_length=AOI_CODE_MAX_LENGTH, blank=True)
    provenance = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "dashboard"
        ordering = ("product_release_id", "aoi_code")
        constraints = (
            models.CheckConstraint(
                condition=~models.Q(aoi_code=""),
                name="dash_product_aoi_not_empty",
            ),
            models.UniqueConstraint(
                fields=("product_release", "aoi_code"),
                name="dash_release_aoi_code_uniq",
            ),
        )
        indexes = (
            models.Index(
                fields=("aoi_code", "product_release"),
                name="dash_aoi_code_release_idx",
            ),
        )

    def clean(self):
        super().clean()
        canonical = normalize_aoi_code(self.aoi_code)
        if canonical is None:
            raise ValidationError({"aoi_code": "Enter a valid AOI code."})
        self.aoi_code = canonical

    def save(self, *args, **kwargs):
        self.clean()
        if self.pk and type(self).objects.filter(pk=self.pk).exclude(
            product_release_id=self.product_release_id,
            aoi_code=self.aoi_code,
            source_value=self.source_value,
            provenance=self.provenance,
        ).exists():
            raise ValidationError(
                "Product AOIs are immutable; create a new release revision."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Product AOIs are historical records and cannot be deleted."
        )

    def __str__(self):
        return "{} / {}".format(self.product_release, self.aoi_code)
