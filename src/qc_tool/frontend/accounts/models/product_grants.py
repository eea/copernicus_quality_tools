from django.conf import settings
from django.db import models


class UserProductGrant(models.Model):
    """Assign one canonical product-definition identifier to a user."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="product_grants",
    )
    product_ident = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        db_table = "account_product_grant"
        ordering = ("product_ident", "pk")
        constraints = (
            models.CheckConstraint(
                condition=~models.Q(product_ident=""),
                name="account_product_key_not_empty",
            ),
            models.UniqueConstraint(
                fields=("user", "product_ident"),
                name="account_product_user_key_uniq",
            ),
        )
        indexes = (
            models.Index(
                fields=("product_ident",),
                name="account_product_ident_idx",
            ),
        )

    def clean(self):
        super().clean()
        from qc_tool.frontend.accounts.services.products import (
            ProductCatalogUnavailable,
        )
        from qc_tool.frontend.accounts.services.products import (
            validate_new_product_ident,
        )

        if self.pk:
            using = self._state.db or "default"
            stored = (
                type(self)
                .objects.using(using)
                .filter(pk=self.pk)
                .values("product_ident", "user_id")
                .first()
            )
            if stored == {
                "product_ident": self.product_ident,
                "user_id": self.user_id,
            }:
                return
        try:
            validate_new_product_ident(self.product_ident)
        except ProductCatalogUnavailable as error:
            from django.core.exceptions import ValidationError

            raise ValidationError(
                {
                    "product_ident": (
                        "Product definitions are unavailable; a new product "
                        "grant cannot be validated."
                    )
                }
            ) from error

    def __str__(self):
        return f"{self.user}: {self.product_ident}"
