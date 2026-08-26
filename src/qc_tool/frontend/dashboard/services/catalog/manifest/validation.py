"""Small validation primitives shared by manifest parsers."""

from ..errors import CatalogError


def required_text(document, key, *, maximum):
    value = document.get(key)
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
    ):
        raise invalid_manifest("{} is invalid".format(key))
    return value


def optional_text(document, key, *, maximum):
    value = document.get(key, "")
    if not isinstance(value, str) or len(value) > maximum:
        raise invalid_manifest("{} is invalid".format(key))
    return value


def invalid_manifest(detail):
    return CatalogError(
        "invalid_manifest",
        "The product catalog manifest is invalid: {}.".format(detail),
    )
