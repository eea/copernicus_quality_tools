"""Stable portable identities and immutable publication context.

Provenance is data, never permission to overwrite a target or execute a source
operation. Locally approved additive receipts bind source identities to target
keys. An origin receipt persists this database's namespace without adding schema.
Read-only previews never create that receipt.
"""

from uuid import NAMESPACE_URL, uuid4, uuid5

from django.contrib.auth import get_user_model
from django.db import connections, transaction

from qc_tool.database.models import TransferReceipt

from .contracts import (
    TransferError, digest, json_value, record_limit,
    require_keys, require_timestamp, require_uuid,
)


PROVENANCE_VERSION = 1
MAX_LEDGER_RECEIPTS = 10_000
MAX_PUBLICATION_RECEIPTS = 1_000
MAX_IDENTITY_BINDINGS = 1_000_000
ORIGIN_PROFILE = "origin"
PUBLICATION_FIELDS = (
    "submission_uuid", "delivery_id", "job_id", "product_release_id",
    "product_unit_id", "product_unit_code", "verified_product_unit_code",
    "input_digest", "requested_at",
)
_UUID_RESOURCES = {"jobs", "submissions"}


def _registry():
    # Lazy import keeps validation and the registry in one central owner.
    from .records import RESOURCE_FIELDS
    return {"accounts": (get_user_model(), ()), **RESOURCE_FIELDS}


def _source_key(resource, value):
    if not isinstance(value, str):
        raise TransferError("A provenance source key must be a canonical string.")
    if resource in _UUID_RESOURCES:
        require_uuid(value, "Provenance source key")
    elif (len(value) > 20 or not value.isascii() or not value.isdecimal()
          or not 0 < int(value) <= 2**63 - 1 or str(int(value)) != value):
        raise TransferError("A provenance source key must be a positive integer string.")
    return value


def _target_key(resource, value):
    if resource in _UUID_RESOURCES:
        require_uuid(value, "Provenance destination key")
    elif type(value) is not int or value <= 0 or value > 2**63 - 1:
        raise TransferError("A provenance destination key must be a positive integer.")
    return value


def _origin(resource, value):
    require_keys(value, ("namespace", "key"), "Record origin")
    require_uuid(value["namespace"], "Record origin namespace")
    _source_key(resource, value["key"])
    return value


def _publication(value, row=None):
    require_keys(value, PUBLICATION_FIELDS, "Original publication identity")
    require_uuid(value["submission_uuid"], "Original submission identity")
    require_uuid(value["job_id"], "Original publication job identity")
    for name in ("delivery_id", "product_release_id", "product_unit_id"):
        if type(value[name]) is not int or not 0 < value[name] <= 2**63 - 1:
            raise TransferError("An original publication parent identity is invalid.")
    from qc_tool.product_units import normalize_product_unit_code
    for name in ("product_unit_code", "verified_product_unit_code"):
        code = value[name]
        if not isinstance(code, str) or normalize_product_unit_code(code) != code:
            raise TransferError("An original publication unit code is invalid.")
    import re
    if not isinstance(value["input_digest"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["input_digest"]):
        raise TransferError("An original publication input checksum is invalid.")
    require_timestamp(value["requested_at"], "Original publication request time")
    if row is not None:
        # Only integer parent identities can differ after rekeying. UUIDs,
        # input identity, unit codes and request evidence must stay unchanged.
        for name in ("submission_uuid", "job_id", "product_unit_code",
                     "verified_product_unit_code", "input_digest", "requested_at"):
            if value[name] != row[name]:
                raise TransferError("Original publication provenance differs from its retained receipt.")
    return value


def _source_record(value, *, inventory=None):
    """Validate original audit data; these source FKs are not target authority."""
    require_keys(value, ("resource", "target_key", "origin", "record"), "Original source record evidence")
    from .records import RESOURCE_FIELDS, _validated_field
    resource = value["resource"]
    if not isinstance(resource, str) or resource not in RESOURCE_FIELDS:
        raise TransferError("Original source evidence names an unsupported business resource.")
    _source_key(resource, value["target_key"])
    _origin(resource, value["origin"])
    if inventory is not None and value["target_key"] not in inventory.get(resource, set()):
        raise TransferError("Original source evidence is outside the included record inventory.")
    model, fields = RESOURCE_FIELDS[resource]
    row = value["record"]
    require_keys(row, fields, "Original source record")
    field_registry = {field.attname: field for field in model._meta.concrete_fields}
    for name in fields:
        _validated_field(field_registry[name], row[name], f"Original {resource}.{name}")
    return value


def _receipt_state(*, using="default"):
    """Read bounded, validated local evidence; imported receipt rows are not run."""
    registry = _registry()
    origins = list(TransferReceipt.objects.using(using).filter(profile=ORIGIN_PROFILE).order_by("pk")[:2])
    if len(origins) > 1:
        raise TransferError("The database has conflicting origin namespaces. Review its transfer history.")
    namespace = None
    if origins:
        receipt = origins[0]
        require_keys(receipt.summary, ("version", "namespace"), "Database origin receipt")
        if type(receipt.summary["version"]) is not int or receipt.summary["version"] != PROVENANCE_VERSION:
            raise TransferError("Unsupported database origin receipt version.")
        namespace = receipt.summary["namespace"]
        require_uuid(namespace, "Database origin namespace")
        if namespace != str(receipt.package_id):
            raise TransferError("Database origin receipt identity is inconsistent.")
    receipts = TransferReceipt.objects.using(using).filter(summary__mode="additive").order_by("pk")
    if receipts.count() > MAX_LEDGER_RECEIPTS:
        raise TransferError("The provenance ledger exceeds its supported receipt bound. A reviewed indexed ledger is required.")
    index, canonical, publications, publication_targets, evidence = {}, {}, {}, {}, {}
    first_operation = None
    bindings = 0
    evidence_scanned = 0
    for receipt in receipts.iterator(chunk_size=100):
        summary = receipt.summary
        if not isinstance(summary, dict) or type(summary.get("version")) is not int or summary["version"] != 1:
            raise TransferError("Unsupported additive provenance receipt version.")
        mappings, sources = summary.get("identity_map"), summary.get("origins")
        if not isinstance(mappings, dict) or not isinstance(sources, dict):
            raise TransferError("An additive receipt has incomplete identity provenance.")
        if set(mappings) - set(registry) or set(sources) - set(registry):
            raise TransferError("An additive receipt names an unsupported provenance resource.")
        for resource, resource_origins in sources.items():
            if not isinstance(resource_origins, dict):
                raise TransferError("An additive receipt's record origins are invalid.")
            for source_key, origin in resource_origins.items():
                _source_key(resource, source_key)
                _origin(resource, origin)
        if first_operation is None:
            first_operation = str(receipt.operation_id)
        for resource, resource_map in mappings.items():
            resource_origins = sources.get(resource, {})
            if not isinstance(resource_map, dict) or not isinstance(resource_origins, dict):
                raise TransferError("An additive receipt identity map is invalid.")
            for source_key, target in resource_map.items():
                _source_key(resource, source_key)
                _target_key(resource, target)
                if source_key not in resource_origins:
                    raise TransferError("An additive receipt is missing a mapped record's origin.")
                origin = _origin(resource, resource_origins[source_key])
                identity = (resource, origin["namespace"], origin["key"])
                previous = index.get(identity)
                if previous is not None and previous != target:
                    raise TransferError("A source record is mapped to contradictory destination identities.")
                index[identity] = target
                # Multiple source aliases may legitimately reuse one exact
                # target row. Its first locally recorded origin is canonical.
                canonical.setdefault((resource, str(target)), json_value(origin))
                bindings += 1
                if bindings > MAX_IDENTITY_BINDINGS:
                    raise TransferError("The provenance ledger exceeds its supported identity bound.")
        recorded_publications = summary.get("publication_identities", {})
        recorded_targets = summary.get("publication_targets", {})
        if (not isinstance(recorded_publications, dict) or not isinstance(recorded_targets, dict)
                or set(recorded_targets) != set(recorded_publications)):
            raise TransferError("An additive receipt's publication provenance is invalid.")
        included_submissions = {str(value) for value in mappings.get("submissions", {}).values()}
        for key, value in recorded_publications.items():
            require_uuid(key, "Recorded publication identity")
            target = _publication(recorded_targets[key])
            _publication(value, target)
            if key not in included_submissions or value["submission_uuid"] != key:
                raise TransferError("Publication provenance is outside its committed record mapping.")
            if key in publications and publications[key] != value:
                raise TransferError("A publication has contradictory original identity evidence.")
            if key in publication_targets and publication_targets[key] != target:
                raise TransferError("A publication has contradictory approved destination evidence.")
            publications[key] = json_value(value)
            publication_targets[key] = json_value(target)
        source_evidence = summary.get("source_evidence", [])
        overrides = summary.get("source_overrides", {})
        # Persisted history is an application ledger, not an uploaded package.
        # Lowering an admission limit must never make committed evidence unreadable.
        if not isinstance(source_evidence, list) or len(source_evidence) > MAX_IDENTITY_BINDINGS or not isinstance(overrides, dict):
            raise TransferError("An additive receipt's original source evidence is invalid or exceeds its bound.")
        included = {resource: {str(target) for target in targets.values()} for resource, targets in mappings.items()}
        candidates = list(source_evidence)
        for resource, source_rows in overrides.items():
            if not isinstance(resource, str) or resource not in registry or resource == "accounts" or not isinstance(source_rows, dict):
                raise TransferError("An additive receipt's source override resource is invalid.")
            for source_key, row in source_rows.items():
                if source_key not in mappings.get(resource, {}) or source_key not in sources.get(resource, {}):
                    raise TransferError("An original source override is outside its committed record mapping.")
                candidates.append({"resource": resource, "target_key": str(mappings[resource][source_key]),
                                   "origin": sources[resource][source_key], "record": row})
        for entry in candidates:
            _source_record(entry, inventory=included)
            evidence[digest(entry)] = json_value(entry)
            evidence_scanned += 1
            if len(evidence) > MAX_IDENTITY_BINDINGS or evidence_scanned > MAX_IDENTITY_BINDINGS:
                raise TransferError("The original source evidence exceeds its supported ledger bound.")
    # A database which already committed a merge has durable local identity
    # material even before its first actual export. This deterministic proposal
    # can be read without writes and is what ensure_namespace later persists.
    if namespace is None and first_operation is not None:
        namespace = str(uuid5(NAMESPACE_URL, "qc-tool-database-origin:" + first_operation))
    return namespace, index, canonical, publications, publication_targets, tuple(evidence.values())


def ensure_namespace():
    """Persist this database's namespace during authorized export execution.

    The caller owns the transfer execution/maintenance barrier. PostgreSQL also
    serializes namespace initialization in SQL. This is intentionally never
    called by an ordinary read-only export preview or validation.
    """
    using = "default"
    with transaction.atomic(using=using):
        connection = connections[using]
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [0x5143544F52494749])
        namespace, _index, _canonical, _publications, _targets, _evidence = _receipt_state(using=using)
        existing = TransferReceipt.objects.using(using).filter(profile=ORIGIN_PROFILE).first()
        if existing is not None:
            return namespace
        namespace = namespace or str(uuid4())
        summary = {"version": PROVENANCE_VERSION, "namespace": namespace}
        checksum = digest({"kind": "qc-tool-database-origin", **summary})
        TransferReceipt.objects.using(using).create(
            package_id=namespace, package_sha256=checksum, operation_id=uuid4(),
            plan_sha256=checksum, profile=ORIGIN_PROFILE, actor=None,
            actor_name="", summary=summary,
        )
        return namespace


def load_identity_index():
    """Return approved (resource, source namespace, source key) → target keys."""
    namespace, index, _canonical, _publications, _targets, _evidence = _receipt_state()
    if namespace is not None:
        bindings = len(index)
        for resource, (model, _fields) in _registry().items():
            for key in model.objects.order_by().values_list(model._meta.pk.attname, flat=True).iterator(chunk_size=1000):
                # Keep the local namespace as an additional alias: it may have
                # appeared in an export before this row acquired an imported
                # origin alias. Export still retains the canonical source.
                identity = (resource, namespace, str(key))
                target = str(key) if resource in _UUID_RESOURCES else key
                if identity in index and index[identity] != target:
                    raise TransferError("A local source identity conflicts with its approved destination mapping.")
                index[identity] = target
                bindings += 1
                if bindings > MAX_IDENTITY_BINDINGS:
                    raise TransferError("The provenance ledger exceeds its supported identity bound.")
    return index


def export_provenance(payload, *, create_namespace=False):
    """Build a v2 envelope, retaining imported aliases and original manifests.

    None keeps a first read-only preview compatible with v1 until a namespace
    is persisted. Already imported records always export their known origins.
    """
    if create_namespace:
        ensure_namespace()
    namespace, _index, canonical, publications, targets, evidence = _receipt_state()
    if namespace is None:
        return None
    identities = {"accounts": {}}
    for row in payload["accounts"]:
        key = row["key"]
        identities["accounts"][key] = canonical.get(("accounts", key), {"namespace": namespace, "key": key})
    for resource, rows in payload["records"].items():
        model = _registry()[resource][0]
        identities[resource] = {}
        for row in rows:
            key = str(row[model._meta.pk.attname])
            identities[resource][key] = canonical.get((resource, key), {"namespace": namespace, "key": key})
    contexts = {}
    for row in payload["records"].get("submissions", []):
        if row["publication_state"] == "published":
            key = row["submission_uuid"]
            if key in targets and {name: row[name] for name in PUBLICATION_FIELDS} != targets[key]:
                raise TransferError("An imported publication differs from its approved destination identity.")
            contexts[row["submission_uuid"]] = publications.get(
                row["submission_uuid"], {name: row[name] for name in PUBLICATION_FIELDS},
            )
    included = {resource: set(values) for resource, values in identities.items()}
    evidence = [entry for entry in evidence if entry["target_key"] in included.get(entry["resource"], set())]
    return {"version": PROVENANCE_VERSION, "namespace": namespace,
            "identities": json_value(identities), "publications": json_value(contexts),
            "source_records": json_value(evidence)}


def validate_provenance(payload, *, enforce_package_limits=True):
    """Strict complete provenance validation with no database/path side effects."""
    value = payload.get("provenance")
    require_keys(value, ("version", "namespace", "identities", "publications", "source_records"), "Record provenance")
    if type(value["version"]) is not int or value["version"] != PROVENANCE_VERSION:
        raise TransferError("Unsupported record provenance version.")
    require_uuid(value["namespace"], "Export origin namespace")
    identities = value["identities"]
    expected = {"accounts": {row["key"] for row in payload["accounts"]}}
    for resource, rows in payload["records"].items():
        model = _registry()[resource][0]
        expected[resource] = {str(row[model._meta.pk.attname]) for row in rows}
    if not isinstance(identities, dict) or set(identities) != set(expected):
        raise TransferError("Provenance resources differ from the record inventory.")
    seen = set()
    for resource, keys in expected.items():
        rows = identities[resource]
        if not isinstance(rows, dict) or set(rows) != keys:
            raise TransferError("Provenance identities differ from the record inventory.")
        for key, origin in rows.items():
            _source_key(resource, key)
            _origin(resource, origin)
            identity = (resource, origin["namespace"], origin["key"])
            if identity in seen:
                raise TransferError("A package contains duplicate source record identities.")
            seen.add(identity)
    publications = value["publications"]
    expected_publications = {row["submission_uuid"]: row for row in payload["records"].get("submissions", [])
                             if row["publication_state"] == "published"}
    if not isinstance(publications, dict) or set(publications) != set(expected_publications):
        raise TransferError("Publication provenance differs from the published record inventory.")
    for key, original in publications.items():
        _publication(original, expected_publications[key])
    evidence = value["source_records"]
    evidence_limit = record_limit() if enforce_package_limits else MAX_IDENTITY_BINDINGS
    if not isinstance(evidence, list) or len(evidence) > evidence_limit:
        raise TransferError("Original source evidence must be a bounded record list.")
    seen = set()
    for entry in evidence:
        _source_record(entry, inventory=expected)
        checksum = digest(entry)
        if checksum in seen:
            raise TransferError("Original source evidence contains duplicate records.")
        seen.add(checksum)
    return json_value(value)


def publication_identity(submission):
    """Read only this submission's approved original/destination JSON leaves.

    Artifact reads do not need another record's identity map or audit history.
    Export/import planning still validates the complete bounded ledger.
    """
    using = getattr(getattr(submission, "_state", None), "db", None) or "default"
    key = str(submission.pk)
    require_uuid(key, "Publication identity")
    context_field = "summary__publication_identities__" + key
    target_field = "summary__publication_targets__" + key
    mapping_field = "summary__identity_map__submissions__" + key
    matches = list(TransferReceipt.objects.using(using).filter(
        summary__mode="additive", summary__publication_identities__has_key=key,
    ).order_by("pk").values("summary__version", context_field, target_field, mapping_field)[:MAX_PUBLICATION_RECEIPTS + 1])
    if len(matches) > MAX_PUBLICATION_RECEIPTS:
        raise TransferError("This publication exceeds its supported provenance receipt bound.")
    original = None
    current = {name: json_value(getattr(submission, name)) for name in PUBLICATION_FIELDS}
    for match in matches:
        if type(match["summary__version"]) is not int or match["summary__version"] != 1:
            raise TransferError("Unsupported additive provenance receipt version.")
        context, target = match[context_field], match[target_field]
        if not isinstance(context, dict) or not isinstance(target, dict):
            raise TransferError("An additive receipt's publication provenance is invalid.")
        if match[mapping_field] != key:
            raise TransferError("Publication provenance is outside its committed record mapping.")
        _publication(target)
        _publication(context, target)
        if target != current:
            raise TransferError("An imported publication differs from its approved destination identity.")
        if original is not None and original != context:
            raise TransferError("A publication has contradictory original identity evidence.")
        original = context
    return json_value(original) if original is not None else None


def get_package_publication_identity(payload, row):
    """Get the validated package overlay without interpreting paths or models."""
    if payload.get("format") not in {2, 3} or (payload.get("format") == 3 and "provenance" not in payload):
        return {name: row[name] for name in PUBLICATION_FIELDS}
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict) or not isinstance(provenance.get("publications"), dict):
        raise TransferError("The package is missing publication provenance.")
    context = provenance["publications"].get(str(row["submission_uuid"]))
    if row["publication_state"] == "published" and context is None:
        raise TransferError("The package is missing an original publication identity.")
    if context is not None:
        _publication(context, row)
    return context
