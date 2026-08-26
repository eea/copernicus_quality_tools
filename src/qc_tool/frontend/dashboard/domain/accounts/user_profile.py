"""Historical dashboard-owned user profile model."""

from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    country = models.CharField(max_length=100, blank=True, null=True)
    product_family = models.CharField(max_length=50, blank=True, null=True)

    class Meta:
        app_label = "dashboard"
