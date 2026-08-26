"""Product presentation and identification service facade."""

from .identification import find_product_description
from .identification import guess_product_ident


def build_product_detail(*args, **kwargs):
    """Load the ORM-backed service lazily to avoid model import cycles."""

    from .detail import build_product_detail as build

    return build(*args, **kwargs)

__all__ = [
    "build_product_detail",
    "find_product_description",
    "guess_product_ident",
]
