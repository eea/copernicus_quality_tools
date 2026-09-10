"""Shared persistence for exact, immutable definition revisions."""

from qc_tool.frontend.dashboard.models import QcDefinition

from .errors import CatalogError


def store_definition(snapshot):
    definition, created = QcDefinition.objects.get_or_create(
        product_ident=snapshot.product_ident,
        digest=snapshot.digest,
        defaults={
            "description": snapshot.description,
            "document": snapshot.document,
            "source_path": snapshot.source_path,
        },
    )
    # Compare with the database's JSON semantics. PostgreSQL can return a JSON
    # exponent such as -3.4028235e38 as a Python integer, which compares unequal
    # to the original binary float despite representing the same JSON number.
    if not created and not QcDefinition.objects.filter(
        pk=definition.pk,
        description=snapshot.description,
        document=snapshot.document,
    ).exists():
        raise CatalogError(
            "definition_digest_collision",
            "The stored QC definition '{}' differs despite an identical digest.".format(
                snapshot.product_ident
            ),
        )
    # The first import location is provenance, not content identity. Deployments
    # can read identical bytes from different checkout/container paths.
    return definition, created
