from django.conf import settings
from django.db import models


class UserRegionGrant(models.Model):
    """Assign one exact, opaque AOI code to a user."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="region_grants",
    )
    aoi_code = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ("aoi_code", "pk")
        constraints = (
            models.CheckConstraint(
                check=~models.Q(aoi_code=""),
                name="accounts_region_aoi_not_empty",
            ),
            models.UniqueConstraint(
                fields=("user", "aoi_code"),
                name="accounts_region_user_aoi_uniq",
            ),
        )
        indexes = (
            models.Index(
                fields=("aoi_code",),
                name="accounts_region_aoi_idx",
            ),
        )

    def __str__(self):
        return f"{self.user}: {self.aoi_code}"
