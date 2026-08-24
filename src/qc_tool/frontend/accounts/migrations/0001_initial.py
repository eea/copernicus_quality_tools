import re

from django.conf import settings
from django.db import migrations
from django.db import models
import django.db.models.deletion


CANONICAL_ROLES = ("default", "product_manager", "admin")
LEGACY_PRODUCT_ROLE = "product_admin"
RETIRED_REGION_ROLES = ("country_manager", "region_manager")
BATCH_SIZE = 1000
API_KEY_DIGEST_PATTERN = re.compile(r"sha256\$[0-9a-f]{64}\Z", re.ASCII)

CAPABILITIES = (
    ("view_deliveries", "Can view deliveries"),
    ("upload_delivery", "Can upload deliveries"),
    ("run_qc", "Can run quality control"),
    ("delete_delivery", "Can delete deliveries"),
    ("submit_delivery", "Can submit deliveries"),
    ("change_password", "Can change own password"),
    ("manage_configuration", "Can manage QC Tool configuration"),
    (
        "view_region_deliveries",
        "Can view deliveries in assigned regions",
    ),
    (
        "view_product_deliveries",
        "Can view deliveries in assigned product family",
    ),
    (
        "view_region_aggregate_report",
        "Can view aggregate reports for assigned regions",
    ),
    (
        "view_product_aggregate_report",
        "Can view aggregate reports for assigned product family",
    ),
)

ROLE_CAPABILITIES = {
    "default": {
        "view_deliveries",
        "upload_delivery",
        "run_qc",
        "delete_delivery",
        "submit_delivery",
        "change_password",
    },
    "product_manager": {
        "view_product_deliveries",
        "view_product_aggregate_report",
    },
    "admin": {codename for codename, _name in CAPABILITIES},
}

REGION_CAPABILITIES = {
    "view_region_deliveries",
    "view_region_aggregate_report",
}
PRODUCT_CAPABILITIES = {
    "view_product_deliveries",
    "view_product_aggregate_report",
}
LEGACY_PERMISSION_RENAMES = {
    "view_country_deliveries": "view_region_deliveries",
    "view_country_aggregate_report": "view_region_aggregate_report",
}


def _revoke_legacy_api_credentials(api_user_model, *, using):
    """Delete plaintext/unsupported credentials during the consolidated migration."""

    invalid_ids = []
    credentials = api_user_model.objects.using(using).values_list(
        "pk",
        "api_key",
    )
    for credential_id, stored_value in credentials.iterator(
        chunk_size=BATCH_SIZE,
    ):
        if (
            not isinstance(stored_value, str)
            or API_KEY_DIGEST_PATTERN.fullmatch(stored_value) is None
        ):
            invalid_ids.append(credential_id)
        if len(invalid_ids) >= BATCH_SIZE:
            api_user_model.objects.using(using).filter(
                pk__in=invalid_ids,
            ).delete()
            invalid_ids = []

    if invalid_ids:
        api_user_model.objects.using(using).filter(pk__in=invalid_ids).delete()


def _relation_details(model, field_name):
    field = model._meta.get_field(field_name)
    return (
        field.remote_field.through,
        field.m2m_field_name(),
        field.m2m_reverse_field_name(),
    )


def _copy_relations(
    through_model,
    *,
    source_field,
    source_id,
    target_field,
    target_id,
    using,
):
    related_ids = through_model.objects.using(using).filter(
        **{f"{target_field}_id": source_id}
    ).values_list(f"{source_field}_id", flat=True)
    through_model.objects.using(using).bulk_create(
        [
            through_model(
                **{
                    f"{source_field}_id": related_id,
                    f"{target_field}_id": target_id,
                }
            )
            for related_id in related_ids.iterator(chunk_size=BATCH_SIZE)
        ],
        batch_size=BATCH_SIZE,
        ignore_conflicts=True,
    )


def _add_user_group_memberships(
    through_model,
    *,
    user_field,
    group_field,
    user_ids,
    group_id,
    using,
):
    through_model.objects.using(using).bulk_create(
        [
            through_model(
                **{
                    f"{user_field}_id": user_id,
                    f"{group_field}_id": group_id,
                }
            )
            for user_id in user_ids
        ],
        batch_size=BATCH_SIZE,
        ignore_conflicts=True,
    )


def _add_direct_permissions(
    through_model,
    *,
    user_field,
    permission_field,
    user_ids,
    permission_ids,
    using,
):
    manager = through_model.objects.using(using)
    rows = []
    for user_id in user_ids:
        for permission_id in permission_ids:
            rows.append(
                through_model(
                    **{
                        f"{user_field}_id": user_id,
                        f"{permission_field}_id": permission_id,
                    }
                )
            )
            if len(rows) >= BATCH_SIZE:
                manager.bulk_create(
                    rows,
                    batch_size=BATCH_SIZE,
                    ignore_conflicts=True,
                )
                rows = []
    if rows:
        manager.bulk_create(
            rows,
            batch_size=BATCH_SIZE,
            ignore_conflicts=True,
        )


def _ensure_capabilities(
    content_type_model,
    permission_model,
    group_model,
    user_model,
    *,
    using,
):
    content_type, _created = content_type_model.objects.using(using).get_or_create(
        app_label="accounts",
        model="accountcapability",
    )
    permissions = permission_model.objects.using(using)
    permission_by_codename = {}
    for codename, name in CAPABILITIES:
        permission, _created = permissions.get_or_create(
            content_type_id=content_type.pk,
            codename=codename,
            defaults={"name": name},
        )
        if permission.name != name:
            permission.name = name
            permission.save(using=using, update_fields=["name"])
        permission_by_codename[codename] = permission

    group_through, group_field, permission_field = _relation_details(
        group_model,
        "permissions",
    )
    user_through, user_field, user_permission_field = _relation_details(
        user_model,
        "user_permissions",
    )
    for old_codename, new_codename in LEGACY_PERMISSION_RENAMES.items():
        old_permission = permissions.filter(
            content_type_id=content_type.pk,
            codename=old_codename,
        ).first()
        if old_permission is None:
            continue
        new_permission = permission_by_codename[new_codename]
        _copy_relations(
            group_through,
            source_field=group_field,
            source_id=old_permission.pk,
            target_field=permission_field,
            target_id=new_permission.pk,
            using=using,
        )
        _copy_relations(
            user_through,
            source_field=user_field,
            source_id=old_permission.pk,
            target_field=user_permission_field,
            target_id=new_permission.pk,
            using=using,
        )
        old_permission.delete(using=using)

    return permission_by_codename


def _merge_group(source, target, user_model, group_model, *, using):
    user_through, user_field, group_field = _relation_details(
        user_model,
        "groups",
    )
    _copy_relations(
        user_through,
        source_field=user_field,
        source_id=source.pk,
        target_field=group_field,
        target_id=target.pk,
        using=using,
    )
    permission_through, group_field, permission_field = _relation_details(
        group_model,
        "permissions",
    )
    _copy_relations(
        permission_through,
        source_field=permission_field,
        source_id=source.pk,
        target_field=group_field,
        target_id=target.pk,
        using=using,
    )
    source.delete(using=using)


def _retire_region_roles(
    groups,
    user_model,
    group_model,
    permission_by_codename,
    *,
    using,
):
    user_group_through, user_field, group_field = _relation_details(
        user_model,
        "groups",
    )
    group_permission_through, permission_group_field, permission_field = (
        _relation_details(group_model, "permissions")
    )
    user_permission_through, direct_user_field, direct_permission_field = (
        _relation_details(user_model, "user_permissions")
    )
    affected_user_ids = set()
    required_permission_ids = {
        permission_by_codename[codename].pk
        for codename in REGION_CAPABILITIES
    }

    for role_name in RETIRED_REGION_ROLES:
        group = groups.filter(name=role_name).first()
        if group is None:
            continue
        member_ids = set(
            user_group_through.objects.using(using)
            .filter(**{f"{group_field}_id": group.pk})
            .values_list(f"{user_field}_id", flat=True)
        )
        affected_user_ids.update(member_ids)
        permission_ids = set(
            group_permission_through.objects.using(using)
            .filter(**{f"{permission_group_field}_id": group.pk})
            .values_list(f"{permission_field}_id", flat=True)
        )
        permission_ids.update(required_permission_ids)
        _add_direct_permissions(
            user_permission_through,
            user_field=direct_user_field,
            permission_field=direct_permission_field,
            user_ids=member_ids,
            permission_ids=permission_ids,
            using=using,
        )
        group.delete(using=using)

    direct_region_user_ids = user_permission_through.objects.using(using).filter(
        **{f"{direct_permission_field}_id__in": required_permission_ids}
    ).values_list(f"{direct_user_field}_id", flat=True)
    affected_user_ids.update(direct_region_user_ids)
    return affected_user_ids


def _synchronize_role_capabilities(
    canonical_groups,
    permission_by_codename,
    *,
    using,
):
    managed_ids = [permission.pk for permission in permission_by_codename.values()]
    for role_name, codenames in ROLE_CAPABILITIES.items():
        group = canonical_groups[role_name]
        stale_permissions = group.permissions.using(using).filter(
            pk__in=managed_ids,
        )
        group.permissions.remove(*stale_permissions)
        group.permissions.add(
            *(permission_by_codename[codename] for codename in codenames)
        )


def bootstrap_accounts(apps, schema_editor):
    """Create the final role model and migrate pre-accounts scope data."""

    using = schema_editor.connection.alias
    user_app_label, user_model_name = settings.AUTH_USER_MODEL.split(".", 1)
    user_model = apps.get_model(user_app_label, user_model_name)
    group_model = apps.get_model("auth", "Group")
    permission_model = apps.get_model("auth", "Permission")
    content_type_model = apps.get_model("contenttypes", "ContentType")
    profile_model = apps.get_model("dashboard", "UserProfile")
    region_grant_model = apps.get_model("accounts", "UserRegionGrant")
    product_grant_model = apps.get_model("accounts", "UserProductGrant")
    api_user_model = apps.get_model("dashboard", "ApiUser")

    # Plaintext credentials from the pre-accounts implementation must never
    # remain usable. Valid versioned digests survive repeat/idempotent runs.
    _revoke_legacy_api_credentials(api_user_model, using=using)

    permission_by_codename = _ensure_capabilities(
        content_type_model,
        permission_model,
        group_model,
        user_model,
        using=using,
    )
    groups = group_model.objects.using(using)
    canonical_groups = {
        role_name: groups.get_or_create(name=role_name)[0]
        for role_name in CANONICAL_ROLES
    }

    user_group_through, user_field, group_field = _relation_details(
        user_model,
        "groups",
    )
    all_user_ids = user_model.objects.using(using).values_list("pk", flat=True)
    _add_user_group_memberships(
        user_group_through,
        user_field=user_field,
        group_field=group_field,
        user_ids=all_user_ids.iterator(chunk_size=BATCH_SIZE),
        group_id=canonical_groups["default"].pk,
        using=using,
    )
    superuser_ids = user_model.objects.using(using).filter(
        is_superuser=True,
    ).values_list("pk", flat=True)
    _add_user_group_memberships(
        user_group_through,
        user_field=user_field,
        group_field=group_field,
        user_ids=superuser_ids.iterator(chunk_size=BATCH_SIZE),
        group_id=canonical_groups["admin"].pk,
        using=using,
    )

    legacy_product_group = groups.filter(name=LEGACY_PRODUCT_ROLE).first()
    if legacy_product_group is not None:
        _merge_group(
            legacy_product_group,
            canonical_groups["product_manager"],
            user_model,
            group_model,
            using=using,
        )

    region_user_ids = _retire_region_roles(
        groups,
        user_model,
        group_model,
        permission_by_codename,
        using=using,
    )

    direct_permission_through, direct_user_field, direct_permission_field = (
        _relation_details(user_model, "user_permissions")
    )
    product_permission_ids = {
        permission_by_codename[codename].pk
        for codename in PRODUCT_CAPABILITIES
    }
    product_user_ids = set(
        user_group_through.objects.using(using)
        .filter(**{f"{group_field}_id": canonical_groups["product_manager"].pk})
        .values_list(f"{user_field}_id", flat=True)
    )
    product_user_ids.update(
        direct_permission_through.objects.using(using)
        .filter(**{f"{direct_permission_field}_id__in": product_permission_ids})
        .values_list(f"{direct_user_field}_id", flat=True)
    )

    region_profiles = profile_model.objects.using(using).filter(
        user_id__in=region_user_ids,
        country__isnull=False,
    ).exclude(country="")
    region_grant_model.objects.using(using).bulk_create(
        [
            region_grant_model(user_id=user_id, aoi_code=country)
            for user_id, country in region_profiles.values_list(
                "user_id",
                "country",
            )
        ],
        batch_size=BATCH_SIZE,
        ignore_conflicts=True,
    )

    product_profiles = profile_model.objects.using(using).filter(
        user_id__in=product_user_ids,
        product_family__isnull=False,
    ).exclude(product_family="")
    product_grants = []
    for user_id, legacy_value in product_profiles.values_list(
        "user_id",
        "product_family",
    ):
        product_ident = legacy_value.strip().casefold()
        if product_ident:
            product_grants.append(
                product_grant_model(
                    user_id=user_id,
                    product_ident=product_ident,
                )
            )
    product_grant_model.objects.using(using).bulk_create(
        product_grants,
        batch_size=BATCH_SIZE,
        ignore_conflicts=True,
    )

    _synchronize_role_capabilities(
        canonical_groups,
        permission_by_codename,
        using=using,
    )


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("dashboard", "0018_alter_delivery_size_bytes"),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountCapability",
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
            ],
            options={
                "managed": False,
                "default_permissions": (),
                "permissions": CAPABILITIES,
            },
        ),
        migrations.CreateModel(
            name="UserRegionGrant",
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
                ("aoi_code", models.CharField(max_length=100)),
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
                        related_name="region_grants",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("aoi_code", "pk"),
                "indexes": (
                    models.Index(
                        fields=["aoi_code"],
                        name="accounts_region_aoi_idx",
                    ),
                ),
                "constraints": (
                    models.CheckConstraint(
                        condition=~models.Q(aoi_code=""),
                        name="accounts_region_aoi_not_empty",
                    ),
                    models.UniqueConstraint(
                        fields=("user", "aoi_code"),
                        name="accounts_region_user_aoi_uniq",
                    ),
                ),
            },
        ),
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
                        condition=~models.Q(product_ident=""),
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
            bootstrap_accounts,
            migrations.RunPython.noop,
        ),
    ]
