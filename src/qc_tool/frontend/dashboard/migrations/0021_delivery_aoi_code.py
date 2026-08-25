"""Adopt or create Delivery.aoi_code across current and former dev schemas."""

from django.db import migrations, models


FIELD_KWARGS = {
    "blank": True,
    "default": None,
    "editable": False,
    "help_text": "Canonical AOI code projected from the latest delivery job.",
    "max_length": 255,
    "null": True,
}


def ensure_column(apps, schema_editor):
    Delivery = apps.get_model("dashboard", "Delivery")
    with schema_editor.connection.cursor() as cursor:
        columns = {
            column.name
            for column in schema_editor.connection.introspection
            .get_table_description(cursor, Delivery._meta.db_table)
        }
    if "aoi_code" in columns:
        return

    field = models.CharField(**FIELD_KWARGS)
    field.set_attributes_from_name("aoi_code")
    field.model = Delivery
    schema_editor.add_field(Delivery, field)


def ensure_index(apps, schema_editor):
    Delivery = apps.get_model("dashboard", "Delivery")
    with schema_editor.connection.cursor() as cursor:
        constraints = schema_editor.connection.introspection.get_constraints(
            cursor,
            Delivery._meta.db_table,
        )
    if "dash_delivery_aoi_idx" in constraints:
        return
    schema_editor.add_index(
        Delivery,
        models.Index(fields=("aoi_code",), name="dash_delivery_aoi_idx"),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("dashboard", "0020_job_aoi_code"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    ensure_column,
                    migrations.RunPython.noop,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="delivery",
                    name="aoi_code",
                    field=models.CharField(**FIELD_KWARGS),
                ),
            ],
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    ensure_index,
                    migrations.RunPython.noop,
                ),
            ],
            state_operations=[
                migrations.AddIndex(
                    model_name="delivery",
                    index=models.Index(
                        fields=("aoi_code",),
                        name="dash_delivery_aoi_idx",
                    ),
                ),
            ],
        ),
    ]
