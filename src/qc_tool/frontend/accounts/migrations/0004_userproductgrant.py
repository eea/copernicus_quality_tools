from django.conf import settings
from django.db import migrations
from django.db import models
import django.db.models.deletion


PRODUCT_MANAGER_ROLE = "product_manager"
PRODUCT_SCOPE_CODENAMES = (
    "view_product_deliveries",
    "view_product_aggregate_report",
)


def _relation_details(model, field_name):
    field = model._meta.get_field(field_name)
    return (
        field.remote_field.through,
        field.m2m_field_name(),
        field.m2m_reverse_field_name(),
    )


def backfill_product_grants(apps, schema_editor):
    """Backfill deterministic normalized legacy values without catalog IO."""

    using = schema_editor.connection.alias
    user_app_label, user_model_name = settings.AUTH_USER_MODEL.split(".", 1)
    user_model = apps.get_model(user_app_label, user_model_name)
    group_model = apps.get_model("auth", "Group")
    permission_model = apps.get_model("auth", "Permission")
    content_type_model = apps.get_model("contenttypes", "ContentType")
    profile_model = apps.get_model("dashboard", "UserProfile")
    grant_model = apps.get_model("accounts", "UserProductGrant")

    affected_user_ids = set()
    product_group = group_model.objects.using(using).filter(
        name=PRODUCT_MANAGER_ROLE,
    ).first()
    if product_group is not None:
        group_through, user_field, group_field = _relation_details(
            user_model,
            "groups",
        )
        affected_user_ids.update(
            group_through.objects.using(using)
            .filter(**{f"{group_field}_id": product_group.pk})
            .values_list(f"{user_field}_id", flat=True)
        )

    content_type = content_type_model.objects.using(using).filter(
        app_label="accounts",
        model="accountcapability",
    ).first()
    if content_type is not None:
        permission_ids = permission_model.objects.using(using).filter(
            content_type_id=content_type.pk,
            codename__in=PRODUCT_SCOPE_CODENAMES,
        ).values_list("pk", flat=True)
        permission_through, user_field, permission_field = _relation_details(
            user_model,
            "user_permissions",
        )
        affected_user_ids.update(
            permission_through.objects.using(using)
            .filter(**{f"{permission_field}_id__in": permission_ids})
            .values_list(f"{user_field}_id", flat=True)
        )

    profiles = profile_model.objects.using(using).filter(
        user_id__in=affected_user_ids,
        product_family__isnull=False,
    ).exclude(product_family="")
    grants = []
    for user_id, legacy_value in profiles.values_list(
        "user_id",
        "product_family",
    ):
        product_ident = legacy_value.strip().casefold()
        if product_ident:
            grants.append(
                grant_model(user_id=user_id, product_ident=product_ident)
            )

    grant_model.objects.using(using).bulk_create(
        grants,
        batch_size=1000,
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("accounts", "0003_userregiongrant_region_permissions"),
        ("dashboard", "0018_alter_delivery_size_bytes"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserProductGrant",
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
                ("product_ident", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="product_grants",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("product_ident", "pk"),
                "indexes": (
                    models.Index(
                        fields=["product_ident"],
                        name="accounts_product_ident_idx",
                    ),
                ),
                "constraints": (
                    models.CheckConstraint(
                        check=~models.Q(product_ident=""),
                        name="accounts_product_key_not_empty",
                    ),
                    models.UniqueConstraint(
                        fields=("user", "product_ident"),
                        name="accounts_product_user_ident_uniq",
                    ),
                ),
            },
        ),
        migrations.RunPython(
            backfill_product_grants,
            migrations.RunPython.noop,
        ),
    ]
