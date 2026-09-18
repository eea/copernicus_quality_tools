"""Account-owned personal API credentials and issuance-time access snapshots."""

from django.conf import settings
from django.db import models


class PersonalAccessToken(models.Model):
    """Named, revocable API token with an issuance-time access snapshot."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="personal_access_tokens",
        db_index=False,  # Covered by account_token_user_name_uniq.
    )
    name = models.CharField(max_length=80)
    secret_digest = models.CharField(max_length=71, unique=True, editable=False)
    token_hint = models.CharField(max_length=16, blank=True, editable=False)
    permission_snapshot = models.JSONField(default=list, editable=False)
    role_snapshot = models.JSONField(default=list, editable=False)
    region_codes_snapshot = models.JSONField(default=list, editable=False)
    product_idents_snapshot = models.JSONField(default=list, editable=False)
    is_administrator_snapshot = models.BooleanField(default=False, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(blank=True, null=True, editable=False)

    class Meta:
        db_table = "account_api_token"
        ordering = ("-created_at", "-pk")
        verbose_name = "personal API token"
        verbose_name_plural = "personal API tokens"
        constraints = (
            models.CheckConstraint(
                condition=~models.Q(name=""),
                name="account_token_name_not_empty",
            ),
            models.UniqueConstraint(
                fields=("user", "name"),
                name="account_token_user_name_uniq",
            ),
        )

    def __str__(self):
        return "{} ({})".format(self.name, self.user)
