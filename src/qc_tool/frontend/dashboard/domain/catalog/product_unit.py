"""Expected product units belonging to a product release."""

from django.core.exceptions import ValidationError
from django.db import models

from qc_tool.product_units import PRODUCT_UNIT_CODE_MAX_LENGTH
from qc_tool.product_units import normalize_product_unit_code

from .product_release import ProductRelease


class ProductUnit(models.Model):
    """One immutable, authoritative expected part of a release."""

    product_release = models.ForeignKey(
        ProductRelease,
        on_delete=models.PROTECT,
        related_name="product_units",
        db_index=False,  # The release/code uniqueness index covers this FK.
    )
    product_unit_code = models.CharField(max_length=PRODUCT_UNIT_CODE_MAX_LENGTH)
    source_value = models.CharField(max_length=PRODUCT_UNIT_CODE_MAX_LENGTH, blank=True)
    provenance = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "dashboard"
        db_table = "catalog_product_unit"
        ordering = ("product_release_id", "product_unit_code")
        constraints = (
            models.CheckConstraint(
                condition=~models.Q(product_unit_code=""),
                name="catalog_product_unit_code_present",
            ),
            models.UniqueConstraint(
                fields=("product_release", "product_unit_code"),
                name="catalog_product_unit_code_uniq",
            ),
        )
        indexes = (
            models.Index(
                fields=("product_unit_code", "product_release"),
                name="catalog_unit_code_release_idx",
            ),
        )

    def clean(self):
        super().clean()
        canonical = normalize_product_unit_code(self.product_unit_code)
        if canonical is None:
            raise ValidationError({"product_unit_code": "Enter a valid product unit code."})
        self.product_unit_code = canonical

    def save(self, *args, **kwargs):
        self.clean()
        if self.pk and type(self).objects.filter(pk=self.pk).exclude(
            product_release_id=self.product_release_id,
            product_unit_code=self.product_unit_code,
            source_value=self.source_value,
            provenance=self.provenance,
        ).exists():
            raise ValidationError(
                "Product units are immutable; create a new release revision."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Product units are historical records and cannot be deleted."
        )

    def __str__(self):
        return "{} / {}".format(self.product_release, self.product_unit_code)
