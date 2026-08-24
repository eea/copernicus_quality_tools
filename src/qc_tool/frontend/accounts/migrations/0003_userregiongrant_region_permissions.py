from django.conf import settings
from django.db import migrations
from django.db import models
import django.db.models.deletion


LEGACY_ROLE_NAME = "country_manager"
REGION_ROLE_NAME = "region_manager"
PERMISSION_RENAMES = (
    (
        "view_country_deliveries",
        "view_region_deliveries",
        "Can view deliveries in assigned regions",
    ),
    (
        "view_country_aggregate_report",
        "view_region_aggregate_report",
        "Can view aggregate reports for assigned regions",
    ),
)


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
            for related_id in related_ids.iterator(chunk_size=1000)
        ],
        batch_size=1000,
        ignore_conflicts=True,
    )


def _users_related_to_ids(
    through_model,
    *,
    user_field,
    related_field,
    related_ids,
    using,
):
    return set(
        through_model.objects.using(using)
        .filter(**{f"{related_field}_id__in": related_ids})
        .values_list(f"{user_field}_id", flat=True)
    )


def _merge_permission_assignments(
    old_permission,
    new_permission,
    *,
    group_model,
    user_model,
    using,
):
    group_through, group_field, permission_field = _relation_details(
        group_model,
        "permissions",
    )
    _copy_relations(
        group_through,
        source_field=group_field,
        source_id=old_permission.pk,
        target_field=permission_field,
        target_id=new_permission.pk,
        using=using,
    )

    user_through, user_field, permission_field = _relation_details(
        user_model,
        "user_permissions",
    )
    _copy_relations(
        user_through,
        source_field=user_field,
        source_id=old_permission.pk,
        target_field=permission_field,
        target_id=new_permission.pk,
        using=using,
    )


def _merge_role_groups(group_model, user_model, *, using):
    groups = group_model.objects.using(using)
    old_group = groups.filter(name=LEGACY_ROLE_NAME).first()
    new_group = groups.filter(name=REGION_ROLE_NAME).first()

    if old_group is None:
        if new_group is None:
            new_group = groups.create(name=REGION_ROLE_NAME)
        return new_group

    if new_group is None:
        old_group.name = REGION_ROLE_NAME
        old_group.save(update_fields=["name"])
        return old_group

    user_through, user_field, group_field = _relation_details(
        user_model,
        "groups",
    )
    _copy_relations(
        user_through,
        source_field=user_field,
        source_id=old_group.pk,
        target_field=group_field,
        target_id=new_group.pk,
        using=using,
    )

    permission_through, group_field, permission_field = _relation_details(
        group_model,
        "permissions",
    )
    permission_ids = permission_through.objects.using(using).filter(
        **{f"{group_field}_id": old_group.pk}
    ).values_list(f"{permission_field}_id", flat=True)
    permission_through.objects.using(using).bulk_create(
        [
            permission_through(
                **{
                    f"{group_field}_id": new_group.pk,
                    f"{permission_field}_id": permission_id,
                }
            )
            for permission_id in permission_ids.iterator(chunk_size=1000)
        ],
        batch_size=1000,
        ignore_conflicts=True,
    )
    old_group.delete()
    return new_group


def migrate_country_scope_to_regions(apps, schema_editor):
    using = schema_editor.connection.alias
    user_app_label, user_model_name = settings.AUTH_USER_MODEL.split(".", 1)
    user_model = apps.get_model(user_app_label, user_model_name)
    group_model = apps.get_model("auth", "Group")
    permission_model = apps.get_model("auth", "Permission")
    content_type_model = apps.get_model("contenttypes", "ContentType")
    profile_model = apps.get_model("dashboard", "UserProfile")
    grant_model = apps.get_model("accounts", "UserRegionGrant")

    content_type, _created = content_type_model.objects.using(using).get_or_create(
        app_label="accounts",
        model="accountcapability",
    )
    permissions = permission_model.objects.using(using)

    role_groups = list(
        group_model.objects.using(using).filter(
            name__in=(LEGACY_ROLE_NAME, REGION_ROLE_NAME),
        )
    )
    user_group_through, user_field, group_field = _relation_details(
        user_model,
        "groups",
    )
    affected_user_ids = _users_related_to_ids(
        user_group_through,
        user_field=user_field,
        related_field=group_field,
        related_ids=[group.pk for group in role_groups],
        using=using,
    )

    old_and_new_codenames = {
        codename
        for old_codename, new_codename, _label in PERMISSION_RENAMES
        for codename in (old_codename, new_codename)
    }
    scoped_permissions = list(
        permissions.filter(
            content_type_id=content_type.pk,
            codename__in=old_and_new_codenames,
        )
    )
    user_permission_through, user_field, permission_field = _relation_details(
        user_model,
        "user_permissions",
    )
    affected_user_ids.update(
        _users_related_to_ids(
            user_permission_through,
            user_field=user_field,
            related_field=permission_field,
            related_ids=[permission.pk for permission in scoped_permissions],
            using=using,
        )
    )

    region_permissions = []
    for old_codename, new_codename, new_name in PERMISSION_RENAMES:
        old_permission = permissions.filter(
            content_type_id=content_type.pk,
            codename=old_codename,
        ).first()
        new_permission = permissions.filter(
            content_type_id=content_type.pk,
            codename=new_codename,
        ).first()

        if old_permission is not None and new_permission is None:
            old_permission.codename = new_codename
            old_permission.name = new_name
            old_permission.save(update_fields=["codename", "name"])
            new_permission = old_permission
        elif old_permission is not None and new_permission is not None:
            _merge_permission_assignments(
                old_permission,
                new_permission,
                group_model=group_model,
                user_model=user_model,
                using=using,
            )
            old_permission.delete()
        elif new_permission is None:
            new_permission = permissions.create(
                content_type_id=content_type.pk,
                codename=new_codename,
                name=new_name,
            )

        if new_permission.name != new_name:
            new_permission.name = new_name
            new_permission.save(update_fields=["name"])
        region_permissions.append(new_permission)

    region_group = _merge_role_groups(group_model, user_model, using=using)
    region_group.permissions.add(*region_permissions)

    profiles = profile_model.objects.using(using).filter(
        user_id__in=affected_user_ids,
        country__isnull=False,
    ).exclude(country="")
    grant_model.objects.using(using).bulk_create(
        [
            grant_model(user_id=user_id, aoi_code=country)
            for user_id, country in profiles.values_list("user_id", "country")
        ],
        batch_size=1000,
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("accounts", "0002_accountcapability"),
        ("dashboard", "0018_alter_delivery_size_bytes"),
    ]

    operations = [
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
                        check=~models.Q(aoi_code=""),
                        name="accounts_region_aoi_not_empty",
                    ),
                    models.UniqueConstraint(
                        fields=("user", "aoi_code"),
                        name="accounts_region_user_aoi_uniq",
                    ),
                ),
            },
        ),
        migrations.AlterModelOptions(
            name="accountcapability",
            options={
                "default_permissions": (),
                "managed": False,
                "permissions": (
                    ("view_deliveries", "Can view deliveries"),
                    ("upload_delivery", "Can upload deliveries"),
                    ("run_qc", "Can run quality control"),
                    ("delete_delivery", "Can delete deliveries"),
                    ("submit_delivery", "Can submit deliveries"),
                    ("change_password", "Can change own password"),
                    (
                        "manage_configuration",
                        "Can manage QC Tool configuration",
                    ),
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
                ),
            },
        ),
        migrations.RunPython(
            migrate_country_scope_to_regions,
            migrations.RunPython.noop,
        ),
    ]
