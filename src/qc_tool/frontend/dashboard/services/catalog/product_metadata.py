"""Bounded, version-checked edits to product presentation metadata."""

import hashlib
import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils.crypto import constant_time_compare

from qc_tool.frontend.accounts.authorization import AccountAccess
from qc_tool.frontend.dashboard.models import Product


METADATA_FIELDS = ("name", "description")
STALE_METADATA_MESSAGE = "This product changed. Reload it and review the current metadata before saving."


def metadata_version(product):
    """Also detect readiness changes that do not advance ``updated_at``."""
    values = {}
    for field in product._meta.concrete_fields:
        value = getattr(product, field.attname)
        values[field.attname] = value.isoformat() if hasattr(value, "isoformat") else value
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def _validated_product(*, product_id, name, description, expected_version, actor):
    if not AccountAccess.from_user(actor).is_administrator:
        raise PermissionDenied("Only QC Tool administrators can edit product metadata.")
    try:
        product = Product.objects.select_for_update().get(pk=product_id)
    except Product.DoesNotExist as error:
        raise ValidationError("This product is no longer available.") from error
    if not isinstance(expected_version, str) or not constant_time_compare(expected_version, metadata_version(product)):
        raise ValidationError(STALE_METADATA_MESSAGE)
    product.name, product.description = name, description
    product.full_clean()
    return product


@transaction.atomic
def validate_product_metadata(*, product_id, name, description, expected_version, actor):
    """Hold the row lock through Django Admin's surrounding form transaction."""
    return _validated_product(product_id=product_id, name=name, description=description,
                              expected_version=expected_version, actor=actor)


@transaction.atomic
def update_product_metadata(*, product_id, name, description, expected_version, actor):
    """Persist only display fields; specification and lifecycle state stay owned."""
    product = _validated_product(product_id=product_id, name=name, description=description,
                                 expected_version=expected_version, actor=actor)
    product.save(update_fields=(*METADATA_FIELDS, "updated_at"))
    return product
