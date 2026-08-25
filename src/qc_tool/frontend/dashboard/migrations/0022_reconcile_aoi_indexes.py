"""Reconcile index names after adopting the former dev AOI columns.

The dev branch created ``Job.aoi_code`` with ``db_index=True`` and therefore
used backend-generated index names. The current branch owns explicit, stable
index names. This migration creates those indexes when needed and removes only
redundant, non-unique indexes over the same single column.
"""

from django.db import migrations, models


AOI_INDEXES = (
    ("Job", "dash_job_aoi_idx"),
    ("Delivery", "dash_delivery_aoi_idx"),
)


def reconcile_indexes(apps, schema_editor):
    for model_name, desired_name in AOI_INDEXES:
        model = apps.get_model("dashboard", model_name)
        constraints = _constraints(schema_editor, model)
        if desired_name not in constraints:
            schema_editor.add_index(
                model,
                models.Index(fields=("aoi_code",), name=desired_name),
            )
            constraints = _constraints(schema_editor, model)

        redundant_names = sorted(
            name
            for name, constraint in constraints.items()
            if name != desired_name
            and constraint.get("index")
            and not constraint.get("unique")
            and tuple(constraint.get("columns") or ()) == ("aoi_code",)
        )
        for redundant_name in redundant_names:
            schema_editor.remove_index(
                model,
                models.Index(
                    fields=("aoi_code",),
                    name=redundant_name,
                ),
            )


def _constraints(schema_editor, model):
    with schema_editor.connection.cursor() as cursor:
        return schema_editor.connection.introspection.get_constraints(
            cursor,
            model._meta.db_table,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("dashboard", "0021_delivery_aoi_code"),
    ]

    operations = [
        migrations.RunPython(
            reconcile_indexes,
            migrations.RunPython.noop,
        ),
    ]
