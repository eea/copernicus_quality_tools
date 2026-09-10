"""Product and immutable QC-definition persistence."""

from dataclasses import replace

from qc_tool.frontend.dashboard.models import Product
from ..revisions import store_definition


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
        definition, created = store_definition(definition_snapshot)
        if created:
            result = replace(
                result,
                definitions_created=result.definitions_created + 1,
            )
        definitions[definition.product_ident] = definition
    return definitions, result
