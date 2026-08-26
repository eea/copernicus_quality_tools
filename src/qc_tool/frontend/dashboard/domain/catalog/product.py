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
        ordering = ("ident",)
        constraints = (
            models.CheckConstraint(
                condition=~models.Q(ident=""),
                name="dash_product_ident_not_empty",
            ),
            models.CheckConstraint(
                condition=~models.Q(name=""),
                name="dash_product_name_not_empty",
            ),
        )

    def __str__(self):
        return "{} — {}".format(self.ident, self.name)
