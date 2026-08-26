"""Snapshot exact executable definitions for durable job associations."""

from django.db import transaction

from qc_tool.frontend.dashboard.models import ProductRelease
from qc_tool.frontend.dashboard.models import QcDefinition

from .errors import CatalogError
from .manifest import load_definition_snapshot


@transaction.atomic
def snapshot_definition_for_job(product_ident):
    """Return an immutable definition and its unambiguous current release."""

    snapshot = load_definition_snapshot(product_ident)
    definition, created = QcDefinition.objects.get_or_create(
        product_ident=snapshot.product_ident,
        digest=snapshot.digest,
        defaults={
            "description": snapshot.description,
            "document": snapshot.document,
            "source_path": snapshot.source_path,
        },
    )
    if not created and (
        definition.description != snapshot.description
        or definition.document != snapshot.document
        or definition.source_path != snapshot.source_path
    ):
        raise CatalogError(
            "definition_digest_collision",
            "The stored QC definition differs despite an identical digest.",
        )
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
