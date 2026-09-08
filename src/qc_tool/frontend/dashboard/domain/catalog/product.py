"""Stable product identity."""

from django.db import models


class Product(models.Model):
    """Stable business product independent of an executable QC definition."""

    ident = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=200)
    description = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "dashboard"
        db_table = "catalog_product"
        ordering = ("ident",)
        constraints = (
            models.CheckConstraint(
                condition=~models.Q(ident=""),
                name="catalog_product_ident_present",
            ),
            models.CheckConstraint(
                condition=~models.Q(name=""),
                name="catalog_product_name_present",
            ),
        )

    def __str__(self):
        return "{} — {}".format(self.ident, self.name)
