"""Snapshot exact executable definitions for durable job associations."""

from django.db import transaction

from qc_tool.frontend.dashboard.models import ProductRelease
from .manifest import load_definition_snapshot
from .revisions import store_definition


@transaction.atomic
def snapshot_definition_for_job(product_ident):
    """Return an immutable definition and its unambiguous current release."""

    snapshot = load_definition_snapshot(product_ident)
    definition, _created = store_definition(snapshot)
    release_ids = list(
        ProductRelease.objects.filter(
            definition_links__qc_definition=definition,
            is_current=True,
        )
        .values_list("pk", flat=True)
        .distinct()[:2]
    )
    release = (
        ProductRelease.objects.get(pk=release_ids[0])
        if len(release_ids) == 1
        else None
    )
    return definition, release
