"""Read-only, explicit portable contracts and schema-drift explanations.

This is a data-reader registry, not schema history, SQL adoption or migration
machinery. Legacy documents retain their exact source fingerprint. Version 3
documents name a reviewed semantic contract; model comments and unrelated Python
methods are not database or transfer-schema changes. Changes to domain validation
require a reviewed VALIDATION_REVISION/contract update and preservation fixtures.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import logging
import os
import re
from uuid import UUID

from django.apps import apps
from django.conf import settings
from django.db import DatabaseError, connection as default_connection
from django.utils.functional import Promise

from qc_tool.database.deployment import SchemaInitializer, _native_type

from .contracts import (
    RECORD_FORMAT_WITH_COMPATIBILITY, SUPPORTED_RECORD_FORMATS, canonical_bytes,
    digest, json_value, require_keys, schema_fingerprint,
)
from .errors import TransferError


logger = logging.getLogger(__name__)
METADATA_FORMAT = "qc-tool-portable-compatibility"
METADATA_VERSION = 1
SCHEMA_DESCRIPTOR_VERSION = 1
CURRENT_CONTRACT_VERSION = 1
VALIDATION_REVISION = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_DESCRIPTOR_BYTES = 2 * 1024**2
MAX_REPORTED_CHANGES = 200
_FIELD_KEYS = ("name", "column", "type", "null", "blank", "primary_key", "unique",
               "max_length", "max_digits", "decimal_places", "choices", "validators",
               "relation", "db_index", "db_collation")


@dataclass(frozen=True)
class ReaderContract:
    version: int
    profiles: frozenset
    record_formats: frozenset


# Only an implemented reader belongs here. Release labels are not reader versions.
SUPPORTED_CONTRACTS = {
    1: ReaderContract(1, frozenset(("accounts", "application")),
                      frozenset((RECORD_FORMAT_WITH_COMPATIBILITY,))),
}


def _symbol(value):
    return value.__module__ + "." + value.__qualname__


def _semantic_value(value):
    """Describe declared Django values without executing package-selected code."""
    if value is None or type(value) in (str, bool, int, float):
        return value
    if isinstance(value, Promise):
        return str(value)
    if isinstance(value, Enum):
        return _semantic_value(value.value)
    if isinstance(value, (date, datetime, Decimal, UUID)):
        return json_value(value)
    if isinstance(value, re.Pattern):
        return {"regex": value.pattern, "flags": value.flags}
    if isinstance(value, (tuple, list)):
        return [_semantic_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_semantic_value(item) for item in value), key=canonical_bytes)
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: _semantic_value(item) for key, item in sorted(value.items())}
    if hasattr(value, "deconstruct"):
        parts = value.deconstruct()
        return {"declaration": _semantic_value(parts)}
    if callable(value) and hasattr(value, "__qualname__"):
        return {"callable": _symbol(value)}
    raise TransferError("An installed schema declaration requires a reviewed compatibility descriptor update.")


def schema_descriptor():
    """Describe installed models and the complete allowlisted record contract.

    Field validators and typed constraints are declarations, never imports or
    instructions read from a package. Runtime database inspection is separate.
    """
    from .records import ACCOUNT_FIELDS, RESOURCE_FIELDS, _assert_contract_registry
    _assert_contract_registry()
    models = []
    for model in sorted(apps.get_models(include_auto_created=True), key=lambda item: item._meta.label_lower):
        if not model._meta.managed or model._meta.proxy:
            continue
        fields = []
        for field in sorted(model._meta.concrete_fields, key=lambda item: item.attname):
            relation = None
            if field.is_relation:
                relation = {"model": field.remote_field.model._meta.label_lower,
                            "field": field.target_field.attname,
                            "on_delete": _symbol(field.remote_field.on_delete)}
            fields.append({
                "name": field.attname, "column": field.column,
                "type": field.get_internal_type(), "null": field.null,
                "blank": field.blank, "primary_key": field.primary_key,
                "unique": field.unique, "max_length": field.max_length,
                "max_digits": getattr(field, "max_digits", None),
                "decimal_places": getattr(field, "decimal_places", None),
                # Labels are presentation and may be translated per request.
                "choices": _semantic_value([value for value, _label in field.flatchoices]),
                "validators": _semantic_value(field.validators), "relation": relation,
                "db_index": field.db_index, "db_collation": getattr(field, "db_collation", None),
            })
        models.append({"model": model._meta.label_lower, "table": model._meta.db_table,
                       "fields": fields,
                       "constraints": _semantic_value(model._meta.constraints),
                       "unique_together": _semantic_value(model._meta.unique_together),
                       "indexes": _semantic_value(model._meta.indexes)})
    return json_value({
        "version": SCHEMA_DESCRIPTOR_VERSION, "models": models,
        "resources": {name: {"model": model._meta.label_lower, "fields": list(fields)}
                      for name, (model, fields) in RESOURCE_FIELDS.items()},
        "account_fields": list(ACCOUNT_FIELDS),
        "source_validation": {
            "policy": "qc-tool-portable-records", "revision": VALIDATION_REVISION,
            "field_values": "declared-django-validators-and-exact-types-v1",
            "dependencies": "complete-foreign-key-and-domain-history-v1",
            "authority": "inactive-new-users-explicit-mappings-no-source-credentials-v1",
            "history": "terminal-jobs-complete-publication-review-v1",
        },
        "time_zone": settings.TIME_ZONE,
        "use_tz": settings.USE_TZ,
    })


def model_contract(profile, descriptor=None, *, version=CURRENT_CONTRACT_VERSION):
    reader = SUPPORTED_CONTRACTS.get(version) if type(version) is int else None
    if reader is None or profile not in reader.profiles:
        raise TransferError("This portable record contract has no supported reader. Preserve the source package; no schema changes were made.")
    return digest({"contract_version": version, "profile": profile,
                   "schema": schema_descriptor() if descriptor is None else descriptor})


def validate_record_contract(payload):
    version = payload.get("contract_version")
    reader = SUPPORTED_CONTRACTS.get(version) if type(version) is int else None
    if (reader is None or payload.get("profile") not in reader.profiles
            or payload.get("format") not in reader.record_formats):
        raise TransferError("Unsupported portable contract version. Keep the source package and use a release with a reviewed compatible reader; no schema changes were made.")
    if payload.get("contract") != model_contract(payload["profile"], version=version):
        raise TransferError("The package semantic model contract differs from this installation. Review its compatibility report and preserve the source package; no schema changes were made.")


def _release():
    return str(os.environ.get("VERSION") or "3.0.0")


def producer_metadata(profile):
    """Metadata for new portable exports; native backups need no ORM readiness."""
    if profile == "database":
        return {"format": METADATA_FORMAT, "version": METADATA_VERSION,
                "profile": "database", "source_release": _release(),
                "contract_version": None, "model_contract": None, "schema": None}
    descriptor = schema_descriptor()
    return {"format": METADATA_FORMAT, "version": METADATA_VERSION,
            "profile": profile, "source_release": _release(),
            "contract_version": CURRENT_CONTRACT_VERSION,
            "model_contract": model_contract(profile, descriptor), "schema": descriptor}


def _checked_descriptor(value):
    if not isinstance(value, dict) or len(canonical_bytes(value)) > MAX_DESCRIPTOR_BYTES:
        raise TransferError("The package schema descriptor is invalid or too large.")
    require_keys(value, ("version", "models", "resources", "account_fields", "source_validation",
                         "time_zone", "use_tz"), "Schema descriptor")
    if type(value["version"]) is not int or value["version"] != SCHEMA_DESCRIPTOR_VERSION:
        raise TransferError("Unsupported schema descriptor version; preserve the original package.")
    if not isinstance(value["models"], list) or len(value["models"]) > 256:
        raise TransferError("The package schema model inventory is invalid.")
    names = set()
    for model in value["models"]:
        require_keys(model, ("model", "table", "fields", "constraints", "unique_together", "indexes"), "Schema model")
        if (not isinstance(model["model"], str) or not isinstance(model["table"], str)
                or model["model"] in names or not isinstance(model["fields"], list)
                or len(model["fields"]) > 512
                or any(not isinstance(model[key], list) for key in ("constraints", "unique_together", "indexes"))):
            raise TransferError("The package schema model identity or fields are invalid.")
        names.add(model["model"])
        field_names = set()
        for field in model["fields"]:
            require_keys(field, _FIELD_KEYS, "Schema field")
            if (not isinstance(field, dict) or not isinstance(field.get("name"), str)
                    or field["name"] in field_names
                    or not isinstance(field["column"], str) or not isinstance(field["type"], str)
                    or any(type(field[key]) is not bool for key in ("null", "blank", "primary_key", "unique", "db_index"))
                    or not isinstance(field["validators"], list) or not isinstance(field["choices"], list)):
                raise TransferError("The package schema field inventory is invalid.")
            field_names.add(field["name"])
            if field["relation"] is not None:
                require_keys(field["relation"], ("model", "field", "on_delete"), "Schema relationship")
                if any(not isinstance(value, str) for value in field["relation"].values()):
                    raise TransferError("The package schema relationship inventory is invalid.")
    if (not isinstance(value["resources"], dict) or not isinstance(value["account_fields"], list)
            or not isinstance(value["source_validation"], dict)):
        raise TransferError("The package schema contract inventory is invalid.")
    return value


def compare_descriptors(source, target):
    """Report differences only. Never infer compatibility or mutate a schema."""
    source, target = _checked_descriptor(source), _checked_descriptor(target)
    changes = []
    def add(kind, path, incoming, current):
        changes.append({"kind": kind, "path": path, "source": incoming, "target": current})
    source_models = {row["model"]: row for row in source["models"]}
    target_models = {row["model"]: row for row in target["models"]}
    for name in sorted(source_models.keys() | target_models.keys()):
        incoming, current = source_models.get(name), target_models.get(name)
        if incoming is None or current is None:
            add("model_added" if incoming is None else "model_removed", name, incoming, current)
            continue
        if incoming["table"] != current["table"]:
            add("table_changed", name, incoming["table"], current["table"])
        source_fields = {row["name"]: row for row in incoming["fields"]}
        target_fields = {row["name"]: row for row in current["fields"]}
        for field_name in sorted(source_fields.keys() | target_fields.keys()):
            old, new = source_fields.get(field_name), target_fields.get(field_name)
            path = name + "." + field_name
            if old is None or new is None:
                add("field_added" if old is None else "field_removed", path, old, new)
                continue
            for key in sorted(old.keys() | new.keys()):
                if old.get(key) != new.get(key):
                    kind = {"type": "type_changed", "null": "nullability_changed",
                            "validators": "validation_changed", "relation": "relationship_changed"}.get(key, "field_changed")
                    add(kind, path + "." + key, old.get(key), new.get(key))
        for key in ("constraints", "unique_together", "indexes"):
            if incoming[key] != current[key]:
                add("constraints_changed" if key != "indexes" else "indexes_changed",
                    name + "." + key, incoming[key], current[key])
    for key in ("resources", "account_fields", "source_validation", "time_zone", "use_tz"):
        if source[key] != target[key]:
            add("validation_changed" if key == "source_validation" else "contract_changed",
                key, source[key], target[key])
    return changes


def postgres_model_columns():
    """Render current managed columns with a disconnected PostgreSQL backend.

    This does not inspect an installed database or call the portable registry.
    It remains useful when native preservation comes from an older schema.
    Only public-schema layout is previewed; activation checks remain definitive.
    """
    from django.db.backends.postgresql.base import DatabaseWrapper

    backend = DatabaseWrapper({"ENGINE": "django.db.backends.postgresql",
                               "NAME": "schema-preview-only", "OPTIONS": {},
                               "TIME_ZONE": None}, alias="qc_schema_preview")
    result = {}
    for model in apps.get_models(include_auto_created=True):
        if not model._meta.can_migrate(backend):
            continue
        table = model._meta.db_table
        if '"' in table or "." in table:
            raise TransferError("Custom model schema names require the restored database's read-only activation check.")
        columns = {}
        for field in model._meta.local_concrete_fields:
            datatype = field.db_type(backend)
            if not isinstance(datatype, str):
                raise TransferError("A model field requires the restored database's read-only activation check.")
            columns[field.column] = {"name": field.column, "type": datatype,
                                     "nullable": field.null}
        result[("public", table)] = columns
    return result


def _native_schema_changes(records):
    """Compare a native archive's actual SQL inventory, never its producer ORM."""
    inventory = records.get("inventory") if isinstance(records, dict) else None
    tables = inventory.get("tables") if isinstance(inventory, dict) else None
    if not isinstance(tables, list):
        return None
    options = default_connection.settings_dict.get("OPTIONS", {}).get("options", "")
    if isinstance(options, str) and "search_path" in options:
        # An unqueried current_schema() cannot be guessed from arbitrary libpq
        # options, functions or role defaults. Do not compare with SQLite types.
        return None
    source = {}
    for table in tables:
        if (not isinstance(table, dict) or not isinstance(table.get("schema"), str)
                or not isinstance(table.get("name"), str) or not isinstance(table.get("columns"), list)):
            return None
        identity = (table["schema"], table["name"])
        if identity in source:
            return None
        columns = {}
        for column in table["columns"]:
            if (not isinstance(column, dict) or not isinstance(column.get("name"), str)
                    or column["name"] in columns or not isinstance(column.get("type"), str)
                    or type(column.get("nullable")) is not bool):
                return None
            columns[column["name"]] = column
        source[identity] = columns
    try:
        expected = postgres_model_columns()
    except (ImportError, TransferError):
        return None
    changes = []
    def add(kind, path, incoming, current):
        changes.append({"kind": kind, "path": path, "source": incoming, "target": current})
    for identity in sorted(source.keys() | expected.keys()):
        incoming, current = source.get(identity), expected.get(identity)
        path = ".".join(identity)
        if incoming is None or current is None:
            add("model_added" if incoming is None else "model_removed", path,
                {"columns": sorted(incoming)} if incoming is not None else None,
                {"columns": sorted(current)} if current is not None else None)
            continue
        for name in sorted(incoming.keys() | current.keys()):
            old, new = incoming.get(name), current.get(name)
            field_path = path + "." + name
            if old is None or new is None:
                add("field_added" if old is None else "field_removed", field_path,
                    {key: old[key] for key in ("type", "nullable")} if old is not None else None,
                    {key: new[key] for key in ("type", "nullable")} if new is not None else None)
                continue
            if _native_type(old["type"], "postgresql") != _native_type(new["type"], "postgresql"):
                add("type_changed", field_path + ".type", old["type"], new["type"])
            if old["nullable"] != new["nullable"]:
                add("nullability_changed", field_path + ".nullable", old["nullable"], new["nullable"])
    return changes


def _native_compatibility(records, metadata, result):
    details = records.get("source_details") if isinstance(records, dict) else None
    source_release = details.get("app_version") if isinstance(details, dict) else None
    if not isinstance(source_release, str) and isinstance(metadata, dict):
        source_release = metadata.get("source_release")
    if isinstance(source_release, str):
        result = {**result, "source_release": source_release}
    changes = _native_schema_changes(records)
    message = "Native PostgreSQL preservation and restore remain available; portable readers do not alter its schema. "
    if changes is None:
        message += "A source-to-model schema preview is unavailable. The restored copy requires the definitive read-only model check before activation."
    elif changes:
        message += "The archived tables/columns differ from current public-schema models. This partial preview does not compare foreign keys, constraints, indexes or privileges. The restored copy cannot be activated until the definitive read-only model check passes."
    else:
        message += "The archived table/column names, PostgreSQL types and nullability match the public-schema model preview. Foreign keys, constraints, indexes and privileges were not compared; activation still requires the definitive read-only model check."
    return {**result, "status": "native-schema-drift" if changes else "native",
            "supported": True, "ready": True,
            "schema_ready": False if changes else None,
            "activation_requires_check": True, "comparison_scope": "public-schema tables and columns",
            "changes": (changes or [])[:MAX_REPORTED_CHANGES],
            "change_count": len(changes or []), "message": message}


def inspect_compatibility(archive):
    """Inspect metadata before record planning, including unsupported packages."""
    records = archive.records
    profile = (archive.manifest or {}).get("profile")
    metadata = (archive.storage or {}).get("compatibility")
    result = {"status": "unsupported", "supported": False, "ready": False,
              "message": "", "changes": [], "change_count": 0,
              "source_release": "Unknown (legacy package)", "target_release": _release()}
    try:
        if profile == "database":
            return _native_compatibility(records, metadata, result)
        if (not isinstance(records, dict) or type(records.get("format")) is not int
                or records["format"] not in SUPPORTED_RECORD_FORMATS):
            raise TransferError("Unsupported record document version. Preserve the original package and use a supported reader.")
        if metadata is None:
            if records.get("format") == RECORD_FORMAT_WITH_COMPATIBILITY:
                raise TransferError("This portable package is missing its required compatibility metadata.")
            supported = records.get("contract") == schema_fingerprint()
            return {**result, "status": "legacy-compatible" if supported else "legacy-unsupported",
                    "supported": supported, "ready": supported,
                    "message": ("Legacy package matches the exact installed model contract." if supported else
                                "This legacy package has no schema descriptor and its exact model fingerprint differs. Preserve the original package; a reviewed compatible reader is required.")}
        require_keys(metadata, ("format", "version", "profile", "source_release", "contract_version", "model_contract", "schema"), "Compatibility metadata")
        if (metadata["format"] != METADATA_FORMAT or type(metadata["version"]) is not int
                or metadata["version"] != METADATA_VERSION or metadata["profile"] != profile
                or profile != records.get("profile") or not isinstance(metadata["source_release"], str)):
            raise TransferError("Unsupported or inconsistent compatibility metadata. Preserve the original package.")
        result["source_release"] = metadata["source_release"]
        descriptor = _checked_descriptor(metadata["schema"])
        changes = compare_descriptors(descriptor, schema_descriptor())
        result.update(changes=changes[:MAX_REPORTED_CHANGES], change_count=len(changes))
        reader = SUPPORTED_CONTRACTS.get(metadata["contract_version"]) if type(metadata["contract_version"]) is int else None
        if reader is None or profile not in reader.profiles:
            raise TransferError("No reviewed reader supports this record contract version. Preserve the original package; no schema changes were made.")
        declared = model_contract(profile, descriptor, version=reader.version)
        if (not _SHA256.fullmatch(str(metadata["model_contract"]))
                or metadata["model_contract"] != declared
                or records.get("format") != RECORD_FORMAT_WITH_COMPATIBILITY
                or type(records.get("contract_version")) is not int
                or records["contract_version"] != reader.version or records.get("contract") != declared):
            raise TransferError("The record contract and declared source schema disagree. Preserve the original package; no schema changes were made.")
        supported = not changes and declared == model_contract(profile)
        return {**result, "status": "compatible" if supported else "schema-drift",
                "supported": supported, "ready": supported,
                "changes": changes[:MAX_REPORTED_CHANGES], "change_count": len(changes),
                "message": ("The package matches the supported semantic record contract." if supported else
                            "The source and installed model contracts differ. Review the differences and preserve the original package. This release cannot convert or migrate the schema.")}
    except TransferError as error:
        return {**result, "message": str(error)}


def require_compatibility(archive):
    report = inspect_compatibility(archive)
    if not report["supported"]:
        raise TransferError(report["message"])
    return report


def target_schema_status(connection=None):
    """Read-only whole-application inspection; never initialize or repair."""
    try:
        report = SchemaInitializer(connection or default_connection).inspect()
    except DatabaseError:
        logger.exception("Could not inspect administrative transfer target schema.")
        return {"ready": False, "state": "unavailable", "problems": [],
                "table_count": None, "message": "Database inspection failed. Check connectivity; no schema changes were made."}
    ready = report["state"] == "ready"
    detail = "; ".join(report["problems"]) or "database is empty"
    return {**report, "ready": ready,
            "message": ("The database matches current models." if ready else
                        "Current model schema is not ready: " + detail + ". Inspection made no changes.")}
