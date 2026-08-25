"""Replace the legacy one-key record with named personal API tokens."""

from collections import Counter
import re

from django.conf import settings
from django.db import migrations
from django.db import models
import django.db.models.deletion


_DIGEST_PATTERN = re.compile(r"sha256\$[0-9a-f]{64}\Z", re.ASCII)
_CANONICAL_ROLES = {"default", "product_manager", "admin"}
_CAPABILITY_CODENAMES = {
    "view_deliveries",
    "upload_delivery",
    "run_qc",
    "delete_delivery",
    "submit_delivery",
    "change_password",
    "manage_own_account",
    "manage_api_credential",
    "manage_configuration",
    "view_region_deliveries",
    "view_product_deliveries",
    "view_region_aggregate_report",
    "view_product_aggregate_report",
}


def migrate_legacy_tokens(apps, schema_editor):
    """Preserve only unambiguous, currently supported legacy digests."""

    using = schema_editor.connection.alias
    legacy_model = apps.get_model("dashboard", "ApiUser")
    token_model = apps.get_model("dashboard", "PersonalAccessToken")
    permission_model = apps.get_model("auth", "Permission")
    region_grant_model = apps.get_model("accounts", "UserRegionGrant")
    product_grant_model = apps.get_model("accounts", "UserProductGrant")
    user_app_label, user_model_name = settings.AUTH_USER_MODEL.split(".", 1)
    user_model = apps.get_model(user_app_label, user_model_name)

    legacy_rows = list(
        legacy_model.objects.using(using).values_list(
            "user_id",
            "api_key",
        )
    )
    digest_counts = Counter(
        digest
        for _user_id, digest in legacy_rows
        if isinstance(digest, str) and _DIGEST_PATTERN.fullmatch(digest)
    )

    for user_id, digest in legacy_rows:
        if digest_counts.get(digest) != 1:
            # Duplicate credentials already failed closed in the old
            # authenticator. Do not make one of them valid during migration.
            continue

        user = user_model.objects.using(using).get(pk=user_id)
        roles = sorted(
            set(
                user.groups.using(using)
                .filter(name__in=_CANONICAL_ROLES)
                .values_list("name", flat=True)
            )
        )
        is_administrator = bool(user.is_superuser or "admin" in roles)

        if is_administrator:
            permissions = sorted(_CAPABILITY_CODENAMES)
        else:
            direct_permissions = permission_model.objects.using(using).filter(
                user=user,
                content_type__app_label="accounts",
                codename__in=_CAPABILITY_CODENAMES,
            )
            group_permissions = permission_model.objects.using(using).filter(
                group__user=user,
                content_type__app_label="accounts",
                codename__in=_CAPABILITY_CODENAMES,
            )
            permissions = sorted(
                set(
                    direct_permissions.values_list("codename", flat=True)
                ).union(
                    group_permissions.values_list("codename", flat=True)
                )
            )

        region_codes = sorted(
            set(
                region_grant_model.objects.using(using)
                .filter(user_id=user_id)
                .exclude(aoi_code="")
                .values_list("aoi_code", flat=True)
            )
        )
        product_idents = sorted(
            set(
                product_grant_model.objects.using(using)
                .filter(user_id=user_id)
                .exclude(product_ident="")
                .values_list("product_ident", flat=True)
            )
        )

        token_model.objects.using(using).create(
            user_id=user_id,
            name="Migrated API token",
            secret_digest=digest,
            token_hint="",
            permission_snapshot=permissions,
            role_snapshot=roles,
            region_codes_snapshot=region_codes,
            product_idents_snapshot=product_idents,
            is_administrator_snapshot=is_administrator,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("dashboard", "0018_alter_delivery_size_bytes"),
    ]

    operations = [
        migrations.CreateModel(
            name="PersonalAccessToken",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=80)),
                (
                    "secret_digest",
                    models.CharField(
                        editable=False,
                        max_length=71,
                        unique=True,
                    ),
                ),
                (
                    "token_hint",
                    models.CharField(blank=True, editable=False, max_length=16),
                ),
                (
                    "permission_snapshot",
                    models.JSONField(default=list, editable=False),
                ),
                (
                    "role_snapshot",
                    models.JSONField(default=list, editable=False),
                ),
                (
                    "region_codes_snapshot",
                    models.JSONField(default=list, editable=False),
                ),
                (
                    "product_idents_snapshot",
                    models.JSONField(default=list, editable=False),
                ),
                (
                    "is_administrator_snapshot",
                    models.BooleanField(default=False, editable=False),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "last_used_at",
                    models.DateTimeField(blank=True, editable=False, null=True),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="personal_access_tokens",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "personal API token",
                "verbose_name_plural": "personal API tokens",
                "ordering": ("-created_at", "-pk"),
                "constraints": (
                    models.CheckConstraint(
                        condition=~models.Q(name=""),
                        name="dashboard_api_token_name_not_empty",
                    ),
                    models.UniqueConstraint(
                        fields=("user", "name"),
                        name="dashboard_api_token_user_name_uniq",
                    ),
                ),
            },
        ),
        migrations.RunPython(migrate_legacy_tokens),
        migrations.DeleteModel(name="ApiUser"),
    ]
