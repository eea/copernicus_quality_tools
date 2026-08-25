"""Canonicalize adopted Job AOIs and rebuild Delivery projections.

Former dev deployments may already have one or both AOI columns, including a
partially applied schema where Job values exist but Delivery values do not.
This bounded, database-only migration reconciles that state without reading
worker result files.
"""

import re
import unicodedata

from django.db import migrations
from django.db import transaction
from django.db.models import OuterRef
from django.db.models import Subquery


BATCH_SIZE = 500
MAX_LENGTH = 255
STANDARD_PATTERNS = (
    re.compile(r"^(?P<aoi_code>[a-z]{2}[0-9]{3}l)(?:[0-9xy])?$", re.I),
    re.compile(r"^(?P<aoi_code>du[0-9]{3})(?:[a-z])?$", re.I),
)
REJECTED_CATEGORIES = frozenset(("Cc", "Cf", "Cs"))


def reconcile_aoi_metadata(apps, schema_editor):
    alias = schema_editor.connection.alias
    Delivery = apps.get_model("dashboard", "Delivery")
    Job = apps.get_model("dashboard", "Job")

    _canonicalize_jobs(Job, alias)
    _project_deliveries(Delivery, Job, alias)


def _canonicalize_jobs(Job, alias):
    last_uuid = None
    while True:
        queryset = Job.objects.using(alias).order_by("job_uuid")
        if last_uuid is not None:
            queryset = queryset.filter(job_uuid__gt=last_uuid)
        jobs = list(queryset.only("job_uuid", "aoi_code")[:BATCH_SIZE])
        if not jobs:
            return

        changed = []
        for job in jobs:
            canonical = _canonicalize(job.aoi_code)
            if job.aoi_code != canonical:
                job.aoi_code = canonical
                changed.append(job)
        if changed:
            Job.objects.using(alias).bulk_update(
                changed,
                ("aoi_code",),
                batch_size=BATCH_SIZE,
            )
        last_uuid = jobs[-1].job_uuid


def _project_deliveries(Delivery, Job, alias):
    latest_aoi = (
        Job.objects.using(alias)
        .filter(delivery_id=OuterRef("pk"))
        .order_by("-date_created", "-job_uuid")
        .values("aoi_code")[:1]
    )
    last_pk = 0
    while True:
        with transaction.atomic(using=alias):
            deliveries = list(
                Delivery.objects.using(alias)
                .select_for_update()
                .filter(pk__gt=last_pk)
                .order_by("pk")
                .annotate(latest_aoi_code=Subquery(latest_aoi))[:BATCH_SIZE]
            )
            if not deliveries:
                return

            changed = []
            for delivery in deliveries:
                if delivery.aoi_code != delivery.latest_aoi_code:
                    delivery.aoi_code = delivery.latest_aoi_code
                    changed.append(delivery)
            if changed:
                Delivery.objects.using(alias).bulk_update(
                    changed,
                    ("aoi_code",),
                    batch_size=BATCH_SIZE,
                )
            last_pk = deliveries[-1].pk


def _canonicalize(value):
    """Frozen copy of the AOI canonicalization rules at migration time."""

    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    if (
        not normalized
        or len(normalized) > MAX_LENGTH
        or any(
            unicodedata.category(character) in REJECTED_CATEGORIES
            for character in normalized
        )
    ):
        return None
    for pattern in STANDARD_PATTERNS:
        match = pattern.fullmatch(normalized)
        if match is not None:
            return match.group("aoi_code").casefold()
    if normalized.isdecimal():
        return str(int(normalized))
    return normalized


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("dashboard", "0022_reconcile_aoi_indexes"),
    ]

    operations = [
        migrations.RunPython(
            reconcile_aoi_metadata,
            migrations.RunPython.noop,
        ),
    ]
