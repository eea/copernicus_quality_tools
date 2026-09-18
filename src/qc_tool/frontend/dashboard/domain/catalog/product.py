"""Stable product identity."""

from django.conf import settings
from django.db import models


class Product(models.Model):
    """Stable business product independent of an executable QC definition."""

    ident = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=200)
    description = models.CharField(max_length=500, blank=True)
    is_active = models.BooleanField(default=True)
    readiness_revision = models.PositiveIntegerField(default=0, editable=False)
    ready_at = models.DateTimeField(blank=True, null=True, editable=False)
    ready_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="finalized_products",
        editable=False,
    )
    ready_by_username = models.CharField(max_length=150, blank=True, editable=False)
    ready_scope_digest = models.CharField(max_length=64, blank=True, editable=False)
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
