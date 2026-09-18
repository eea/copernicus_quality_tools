"""Small managed catalog fixtures for frontend workflow tests."""

import hashlib
import json

from qc_tool.frontend.dashboard.models import (
    Product, ProductRelease, ProductReleaseDefinition, QcDefinition,
)


def managed_definition(ident, *, description=None, document=None):
    """Create one active catalog product and its current definition link."""

    document = document or {"description": description or ident, "steps": []}
    definition = QcDefinition.objects.create(
        product_ident=ident,
        digest=hashlib.sha256(json.dumps(document).encode()).hexdigest(),
        description=document["description"], document=document,
        source_path="test:" + ident,
    )
    product = Product.objects.create(ident=ident, name=document["description"])
    release = ProductRelease.objects.create(
        product=product, release_key=ident, revision=1,
        catalog_digest=definition.digest, is_current=True,
    )
    ProductReleaseDefinition.objects.create(
        product_release=release, qc_definition=definition, is_primary=True,
    )
    return definition, release
