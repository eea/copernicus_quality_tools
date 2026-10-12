"""Historical filename protection without inventing publication evidence.

A submission timestamp without a retained receipt is legacy history. Its
original filename prevents another admission, including across owners and
deleted rows. This does not identify renamed ZIPs or establish approval.
"""

from django.db.models import Value
from django.db.models.functions import Lower

from qc_tool.frontend.dashboard.models import Delivery


class LegacyDeliveryAlreadySubmitted(ValueError):
    code = "legacy_delivery_already_submitted"
    message = (
        "A delivery with this filename was already submitted in the legacy QC Tool. "
        "Contact an administrator to reconcile the historical submission."
    )


def require_available_legacy_filename(filename, *, exclude_delivery_id=None):
    """Reject a submitted historical basename without exposing its record.

    Database LOWER makes ASCII filename comparison case insensitive on both
    supported backends and uses the submitted-filename expression index.
    Callers must authorize the requested action before consulting history.
    """

    history = Delivery.objects.alias(legacy_filename=Lower("filename")).filter(
        legacy_filename=Lower(Value(filename)),
        date_submitted__isnull=False,
        submission__isnull=True,
    )
    if exclude_delivery_id is not None:
        history = history.exclude(pk=exclude_delivery_id)
    if history.exists():
        raise LegacyDeliveryAlreadySubmitted(LegacyDeliveryAlreadySubmitted.message)
