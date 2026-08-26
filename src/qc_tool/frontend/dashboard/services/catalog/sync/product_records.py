"""Product and immutable QC-definition persistence."""

from dataclasses import replace

from qc_tool.frontend.dashboard.models import Product
from qc_tool.frontend.dashboard.models import QcDefinition

from ..errors import CatalogError


def synchronize_product(snapshot, result):
    product, created = Product.objects.get_or_create(
        ident=snapshot.product_ident,
        defaults={
            "name": snapshot.product_name,
            "description": snapshot.product_description,
        },
    )
    if created:
        result = replace(result, products_created=result.products_created + 1)
    elif (
        product.name != snapshot.product_name
        or product.description != snapshot.product_description
    ):
        product.name = snapshot.product_name
        product.description = snapshot.product_description
        product.save(update_fields=("name", "description", "updated_at"))
        result = replace(result, products_updated=result.products_updated + 1)
    return product, result


def synchronize_definitions(snapshot, result):
    definitions = {}
    for definition_snapshot in snapshot.definitions:
        definition, created = QcDefinition.objects.get_or_create(
            product_ident=definition_snapshot.product_ident,
            digest=definition_snapshot.digest,
            defaults={
                "description": definition_snapshot.description,
                "document": definition_snapshot.document,
                "source_path": definition_snapshot.source_path,
            },
        )
        if created:
            result = replace(
                result,
                definitions_created=result.definitions_created + 1,
            )
        elif _definition_has_drifted(definition, definition_snapshot):
            raise CatalogError(
                "definition_digest_collision",
                "A stored QC definition differs despite an identical digest.",
            )
        definitions[definition.product_ident] = definition
    return definitions, result


def _definition_has_drifted(definition, snapshot):
    return (
        definition.description != snapshot.description
        or definition.document != snapshot.document
        or definition.source_path != snapshot.source_path
    )
