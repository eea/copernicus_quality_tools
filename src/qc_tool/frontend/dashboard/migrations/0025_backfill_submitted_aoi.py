"""Copy legacy AOI projections into the explicitly submitted AOI fields.

The legacy ``aoi_code`` columns remain in place for API compatibility.  This
migration only fills missing values and therefore preserves data already
written through the new dual-write lifecycle.
"""

from django.db import migrations
from django.db.models import F
from django.db.models import Q


def backfill_submitted_aoi(apps, schema_editor):
    alias = schema_editor.connection.alias
    Delivery = apps.get_model("dashboard", "Delivery")
    Job = apps.get_model("dashboard", "Job")

    _copy_nonblank_legacy_values(Job, using=alias)
    _copy_nonblank_legacy_values(Delivery, using=alias)


def _copy_nonblank_legacy_values(model, *, using):
    (
        model.objects.using(using)
        .filter(Q(aoi_code_submitted__isnull=True) | Q(aoi_code_submitted=""))
        .exclude(aoi_code__isnull=True)
        .exclude(aoi_code="")
        .update(aoi_code_submitted=F("aoi_code"))
    )


class Migration(migrations.Migration):
    dependencies = [
        ("dashboard", "0024_catalog_submissions"),
    ]

    operations = [
        migrations.RunPython(
            backfill_submitted_aoi,
            migrations.RunPython.noop,
        ),
    ]
