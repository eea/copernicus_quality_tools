from django.conf import settings
from django.db import migrations


ROLE_NAMES = (
    "default",
    "country_manager",
    "product_manager",
    "admin",
)

LEGACY_PRODUCT_MANAGER_GROUP = "product_admin"


def _add_group_memberships(
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
        batch_size=1000,
        ignore_conflicts=True,
    )


def create_role_groups(apps, schema_editor):
    user_app_label, user_model_name = settings.AUTH_USER_MODEL.split(".", 1)
    user_model = apps.get_model(user_app_label, user_model_name)
    group_model = apps.get_model("auth", "Group")
    using = schema_editor.connection.alias
    groups = group_model.objects.using(using)

    canonical_groups = {}
    for name in ROLE_NAMES:
        canonical_groups[name], _created = groups.get_or_create(name=name)

    groups_field = user_model._meta.get_field("groups")
    membership_model = groups_field.remote_field.through
    membership_user_field = groups_field.m2m_field_name()
    membership_group_field = groups_field.m2m_reverse_field_name()
    all_user_ids = user_model.objects.using(using).values_list("pk", flat=True)
    _add_group_memberships(
        membership_model,
        user_field=membership_user_field,
        group_field=membership_group_field,
        user_ids=all_user_ids.iterator(chunk_size=1000),
        group_id=canonical_groups["default"].pk,
        using=using,
    )

    superuser_ids = user_model.objects.using(using).filter(
        is_superuser=True,
    ).values_list("pk", flat=True)
    _add_group_memberships(
        membership_model,
        user_field=membership_user_field,
        group_field=membership_group_field,
        user_ids=superuser_ids.iterator(chunk_size=1000),
        group_id=canonical_groups["admin"].pk,
        using=using,
    )

    legacy_product_group = groups.filter(
        name=LEGACY_PRODUCT_MANAGER_GROUP,
    ).first()
    if legacy_product_group is None:
        return

    legacy_user_ids = membership_model.objects.using(using).filter(
        **{f"{membership_group_field}_id": legacy_product_group.pk}
    ).values_list(f"{membership_user_field}_id", flat=True)
    _add_group_memberships(
        membership_model,
        user_field=membership_user_field,
        group_field=membership_group_field,
        user_ids=legacy_user_ids.iterator(chunk_size=1000),
        group_id=canonical_groups["product_manager"].pk,
        using=using,
    )

    group_permission_model = group_model.permissions.through
    permission_ids = group_permission_model.objects.using(using).filter(
        group_id=legacy_product_group.pk,
    ).values_list("permission_id", flat=True)
    group_permission_model.objects.using(using).bulk_create(
        [
            group_permission_model(
                group_id=canonical_groups["product_manager"].pk,
                permission_id=permission_id,
            )
            for permission_id in permission_ids.iterator(chunk_size=1000)
        ],
        batch_size=1000,
        ignore_conflicts=True,
    )
    legacy_product_group.delete()


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(create_role_groups, migrations.RunPython.noop),
    ]
