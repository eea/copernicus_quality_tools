"""Top-level schema parsing for decoded product catalog manifests."""

from qc_tool.product_security import normalize_product_ident

from ..contracts import CatalogSnapshot
from .constants import MAX_RELEASES
from .release_parser import parse_release_document
from .validation import invalid_manifest
from .validation import optional_text
from .validation import required_text


def parse_manifest_document(document, *, definition_loader):
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise invalid_manifest("schema_version must be 1")
    products = document.get("products")
    if not isinstance(products, list):
        raise invalid_manifest("products must be a list")

    releases = []
    product_idents = set()
    release_revisions = set()
    for product_document in products:
        if not isinstance(product_document, dict):
            raise invalid_manifest("every product must be an object")
        product_ident = normalize_product_ident(
            required_text(
                product_document,
                "ident",
                maximum=64,
            )
        )
        if product_ident is None:
            raise invalid_manifest(
                "product ident must be a routable, non-reserved identifier"
            )
        product_name = required_text(product_document, "name", maximum=200)
        product_description = optional_text(
            product_document,
            "description",
            maximum=500,
        )
        if product_ident in product_idents:
            raise invalid_manifest("product identifiers must be unique")
        product_idents.add(product_ident)

        product_releases = product_document.get("releases")
        if not isinstance(product_releases, list) or not product_releases:
            raise invalid_manifest(
                "every product must declare at least one release"
            )
        for release_document in product_releases:
            release = parse_release_document(
                release_document,
                product_ident=product_ident,
                product_name=product_name,
                product_description=product_description,
                definition_loader=definition_loader,
            )
            identity = (release.release_key, release.revision)
            if identity in release_revisions:
                raise invalid_manifest(
                    "release key and revision pairs must be unique"
                )
            release_revisions.add(identity)
            releases.append(release)
            if len(releases) > MAX_RELEASES:
                raise invalid_manifest("the manifest declares too many releases")
    return CatalogSnapshot(releases=tuple(releases))
