"""Publication hierarchy from explicit catalog versions, never product dates."""

import re

from ..errors import PublicationError


_UNSAFE_COMPONENT = re.compile(r"[^a-zA-Z0-9._-]+")
_SHA256 = re.compile(r"[0-9a-f]{64}")


def publication_components(reserved):
    """Require the exact product, catalog revision and executable definition."""

    identifiers = (
        reserved.product_id, reserved.product_release_id,
        reserved.release_revision, reserved.product_unit_id,
    )
    if (
        any(type(value) is not int or value <= 0 for value in identifiers)
        or not isinstance(reserved.definition_digest, str)
        or not _SHA256.fullmatch(reserved.definition_digest)
    ):
        raise PublicationError(
            "publication_identity_unavailable",
            "The submission needs an exact product, specification revision and definition checksum.",
            409,
        )
    return (
        "product-{}-{}".format(reserved.product_id, _component(reserved.product_ident)),
        "specification-{}-{}-r{}-{}".format(
            reserved.product_release_id, _component(reserved.release_key),
            reserved.release_revision, reserved.definition_digest,
        ),
        "product-unit-{}-{}".format(reserved.product_unit_id, _component(reserved.product_unit_code)),
    )


def legacy_publication_components(reserved):
    """Both historical layouts remain readable without relabelling files."""

    release = "release-{}-{}".format(reserved.product_release_id, _legacy_component(reserved.release_key))
    unit = "{}-{}".format(reserved.product_unit_id, _legacy_component(reserved.product_unit_code))
    return ((release, "product-unit-" + unit), (release, "aoi-" + unit))


def _component(value):
    if not isinstance(value, str) or not value.strip():
        raise PublicationError("publication_identity_unavailable", "A publication identity is missing.", 409)
    component = _UNSAFE_COMPONENT.sub("-", value).strip(".-_").lower()[:80]
    if not component:
        raise PublicationError("publication_identity_unavailable", "A publication identity has no safe folder name.", 409)
    return component


def _legacy_component(value):
    # Match old deterministic names exactly, including their historical fallback.
    return (_UNSAFE_COMPONENT.sub("-", str(value)).strip(".-_").lower() or "value")[:80]
