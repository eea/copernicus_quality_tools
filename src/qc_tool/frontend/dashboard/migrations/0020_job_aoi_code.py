"""Adopt or create Job.aoi_code across current and former dev schemas."""

from django.db import migrations, models


FIELD_KWARGS = {
    "blank": True,
    "default": None,
    "editable": False,
    "help_text": "Canonical AOI code reported by the delivery job result.",
    "max_length": 255,
    "null": True,
}


def ensure_column(apps, schema_editor):
    Job = apps.get_model("dashboard", "Job")
    with schema_editor.connection.cursor() as cursor:
        columns = {
            column.name
            for column in schema_editor.connection.introspection
            .get_table_description(cursor, Job._meta.db_table)
        }
    if "aoi_code" in columns:
        return

    field = models.CharField(**FIELD_KWARGS)
    field.set_attributes_from_name("aoi_code")
    field.model = Job
    schema_editor.add_field(Job, field)


def ensure_index(apps, schema_editor):
    Job = apps.get_model("dashboard", "Job")
    with schema_editor.connection.cursor() as cursor:
        constraints = schema_editor.connection.introspection.get_constraints(
            cursor,
            Job._meta.db_table,
        )
    if "dash_job_aoi_idx" in constraints:
        return
    schema_editor.add_index(
        Job,
        models.Index(fields=("aoi_code",), name="dash_job_aoi_idx"),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("dashboard", "0019_personal_access_tokens"),
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
                    model_name="job",
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
                    model_name="job",
                    index=models.Index(
                        fields=("aoi_code",),
                        name="dash_job_aoi_idx",
                    ),
                ),
            ],
        ),
    ]
