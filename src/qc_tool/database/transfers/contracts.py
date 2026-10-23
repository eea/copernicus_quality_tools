"""Explicit, versioned data-transfer contracts; never schema migration code."""

import hashlib
import inspect
import json
from datetime import datetime
from uuid import UUID

from django.apps import apps
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone

from .errors import TransferError


FORMAT_VERSION = 1
RECORD_FORMAT_WITH_PROVENANCE = 2
RECORD_FORMAT_WITH_COMPATIBILITY = 3
SUPPORTED_RECORD_FORMATS = frozenset((FORMAT_VERSION, RECORD_FORMAT_WITH_PROVENANCE,
                                      RECORD_FORMAT_WITH_COMPATIBILITY))
CONTRACT_REVISION = 1
MAX_RECORDS = 250_000


def record_limit():
    value = getattr(settings, "QC_TOOL_TRANSFER_MAX_RECORDS", MAX_RECORDS)
    if type(value) is not int or value < 1 or value > 1_000_000:
        raise TransferError("QC_TOOL_TRANSFER_MAX_RECORDS must be an integer between 1 and 1000000.")
    return value


class _ExactJSONEncoder(DjangoJSONEncoder):
    def default(self, value):
        if isinstance(value, datetime):
            return value.isoformat()
        return super().default(value)


def canonical_bytes(value):
    """Encode one deterministic JSON document, refusing non-finite numbers."""
    try:
        return json.dumps(value, cls=_ExactJSONEncoder, ensure_ascii=False,
                          sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise TransferError("The transfer contains values that are not supported JSON.") from error


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def json_value(value):
    return json.loads(canonical_bytes(value))


def schema_fingerprint():
    """Bind draft packages to the exact current model/validation definitions.

    Version labels are not a schema freeze. A changed model requires a newly
    reviewed reader contract, rather than silently dropping/defaulting fields.
    Source digests also detect changes to model-level domain validation.
    """
    result = []
    for model in sorted(apps.get_models(), key=lambda item: item._meta.label_lower):
        if not model._meta.managed or model._meta.app_label not in {"auth", "accounts", "dashboard"}:
            continue
        fields = []
        for field in model._meta.concrete_fields:
            target = field.remote_field.model._meta.label_lower if field.is_relation else None
            fields.append({
                "name": field.attname, "type": field.get_internal_type(),
                "null": field.null, "blank": field.blank, "primary_key": field.primary_key,
                "unique": field.unique, "max_length": field.max_length,
                "choices": list(field.flatchoices), "target": target,
            })
        try:
            source = inspect.getsource(model)
        except (OSError, TypeError) as error:
            raise TransferError("Cannot establish the installed model contract.") from error
        result.append({"model": model._meta.label_lower, "table": model._meta.db_table,
                       "fields": fields, "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                       "constraints": [repr(rule) for rule in model._meta.constraints]})
    return digest({"revision": CONTRACT_REVISION, "models": result,
                   "time_zone": settings.TIME_ZONE, "use_tz": settings.USE_TZ})


def require_keys(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise TransferError(f"{label} has missing or unsupported fields.")


def require_timestamp(value, label):
    if not isinstance(value, str) or "T" not in value:
        raise TransferError(f"{label} must be an ISO timestamp matching the installation timezone policy.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise TransferError(f"{label} must be an ISO timestamp matching the installation timezone policy.") from error
    if timezone.is_naive(parsed) == settings.USE_TZ:
        raise TransferError(f"{label} must match the installation timezone policy.")
    return parsed


def require_uuid(value, label):
    if not isinstance(value, str):
        raise TransferError(f"{label} must be a canonical UUID.")
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise TransferError(f"{label} must be a canonical UUID.") from error
    if str(parsed) != value:
        raise TransferError(f"{label} must be a canonical UUID.")
    return parsed
