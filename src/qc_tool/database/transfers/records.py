"""Allowlisted record graphs and reviewed transfer plans.

The application profile adds a reviewed graph through the central merge planner.
Durable identity maps preserve immutable publication manifests after rekeying.
Accounts are a separate portable profile with selected inactive additions,
explicit identity reuse and bounded name/email updates. Credentials and source
authority are never imported.
"""

import re
from collections import Counter

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.models import Q
from django.utils import timezone

from qc_tool.common import JOB_ERROR, JOB_FAILED, JOB_LOST, JOB_OK, JOB_PARTIAL, JOB_TIMEOUT
from qc_tool.frontend.dashboard.models import (
    Delivery, DeliverySubmission, Job, Product, ProductRelease,
    ProductReleaseDefinition, ProductUnit, QcDefinition, S3Info,
    SubmissionConflict, SubmissionConflictEvent, SubmissionReviewEvent,
)
from qc_tool.product_security import normalize_product_ident
from qc_tool.product_units import normalize_product_unit_code

from .contracts import (
    FORMAT_VERSION, RECORD_FORMAT_WITH_PROVENANCE, RECORD_FORMAT_WITH_COMPATIBILITY,
    SUPPORTED_RECORD_FORMATS,
    TransferError, canonical_bytes, digest, json_value,
    require_keys, require_timestamp, require_uuid, schema_fingerprint, record_limit,
)
from .errors import RecordLimitError

# Every resource and stored field is an explicit reviewed contract. New models
# or fields must be added deliberately; uploaded model names never select code.
RESOURCE_FIELDS = {
    "products": (Product, "id ident name description is_active readiness_revision ready_at ready_by_id ready_by_username ready_scope_digest created_at updated_at"),
    "definitions": (QcDefinition, "id product_ident digest description document source_path imported_at"),
    "releases": (ProductRelease, "id product_id release_key revision description catalog_digest source_kind coverage_state is_current supersedes_id created_at approved_at approved_by_id"),
    "release_definitions": (ProductReleaseDefinition, "id product_release_id qc_definition_id is_primary"),
    "units": (ProductUnit, "id product_release_id product_unit_code source_value provenance created_at"),
    "remote_sources": (S3Info, "id host bucketname key_prefix"),
    "deliveries": (Delivery, "id user_id filename size_bytes date_uploaded date_submitted product_ident product_description product_unit_code verified_product_unit_code content_sha256 is_deleted s3_id"),
    "jobs": (Job, "job_uuid delivery_id date_created date_started date_finished job_status product_ident product_description product_unit_code verified_product_unit_code skip_steps requested_by_id requested_by_username request_source requested_api_token_id requested_api_token_name product_release_id qc_definition_id input_sha256 reference_period"),
    "submissions": (DeliverySubmission, "submission_uuid delivery_id job_id product_release_id product_unit_id product_unit_code verified_product_unit_code submitted_by_id submitted_by_username request_channel api_token_id api_token_name publication_state review_state review_version requested_at publication_claimed_at publication_token published_at artifact_key artifact_digest input_digest failure_code failure_message"),
    "conflicts": (SubmissionConflict, "id product_unit_id state version selected_submission_id opened_at resolved_at resolved_by_id resolved_by_username resolution_notes updated_at"),
    "conflict_events": (SubmissionConflictEvent, "id conflict_id version event_type actor_id actor_username selected_submission_id notes created_at"),
    "review_events": (SubmissionReviewEvent, "id submission_id version decision actor_id actor_username notes created_at"),
}
RESOURCE_FIELDS = {name: (model, tuple(fields.split())) for name, (model, fields) in RESOURCE_FIELDS.items()}
ACCOUNT_FIELDS = ("key", "username", "first_name", "last_name", "email", "date_joined", "grants", "roles")
PAYLOAD_FIELDS = ("format", "profile", "contract", "created_at", "selection", "accounts", "records")
PROVENANCE_PAYLOAD_FIELDS = (*PAYLOAD_FIELDS, "provenance")
FINAL_JOB_STATUSES = {JOB_ERROR, JOB_FAILED, JOB_LOST, JOB_OK, JOB_PARTIAL, JOB_TIMEOUT}
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _assert_contract_registry():
    expected_models = {model for model, _fields in RESOURCE_FIELDS.values()}
    installed_models = {model for model in apps.get_models() if model._meta.app_label == "dashboard" and model._meta.managed}
    if installed_models != expected_models:
        raise TransferError("The business model inventory requires a reviewed transfer contract update.")
    excluded = {S3Info: {"credential_ref"}, Job: {"worker_url"}}
    for name, (model, fields) in RESOURCE_FIELDS.items():
        expected = {field.attname for field in model._meta.concrete_fields} - excluded.get(model, set())
        if set(fields) != expected:
            raise TransferError(f"The {name} transfer contract requires a reviewed update.")


def _export_users(profile, user_ids, include_unreferenced_accounts):
    """Share exact account selection between SQL counts and serialization."""
    _assert_contract_registry()
    if not isinstance(profile, str) or profile not in {"accounts", "application"}:
        raise TransferError("Choose a supported transfer profile.")
    if profile == "application" and user_ids is not None:
        raise TransferError("Application restore requires the complete business graph; use accounts for a user selection.")
    User = get_user_model()
    users = User.objects.order_by("pk")
    if profile == "application" and not include_unreferenced_accounts:
        # Derive account dependencies from the reviewed model registry, including
        # approvers, requesters and reviewers as well as delivery owners. Numeric
        # identities remain source identities; the importer owns target mapping.
        required = Q(pk__in=[])
        for model, fields in RESOURCE_FIELDS.values():
            for field in model._meta.concrete_fields:
                if field.is_relation and field.related_model is User and field.attname in fields:
                    required |= Q(pk__in=model.objects.order_by().values(field.attname))
        users = users.filter(required)
    if user_ids is not None:
        if not isinstance(user_ids, (list, tuple)) or any(type(value) is not int or value <= 0 for value in user_ids):
            raise TransferError("Select valid account IDs.")
        users = users.filter(pk__in=user_ids)
        if users.count() != len(set(user_ids)):
            raise TransferError("An account selection no longer exists.")
    return users


def export_record_counts(profile="accounts", user_ids=None, *, include_unreferenced_accounts=True):
    """Count the complete selected graph in SQL, without loading row contents.

    The caller owns the same maintenance barrier used for the actual snapshot.
    Counts are a capacity preflight, not a substitute for graph validation.
    """
    users = _export_users(profile, user_ids, include_unreferenced_accounts)
    return {"accounts": users.count(), **({name: model.objects.count()
            for name, (model, _fields) in RESOURCE_FIELDS.items()} if profile == "application" else {})}


def export_records(profile="accounts", user_ids=None, *, enforce_package_limits=True,
                   include_unreferenced_accounts=True, semantic_contract=False):
    """Create a JSON-safe record document inside the caller's snapshot barrier.

    Portable packages retain their configured record bound. Only trusted
    current-application readiness checks may opt out of that packaging limit;
    they still perform the complete field, dependency and business validation.
    """
    users = _export_users(profile, user_ids, include_unreferenced_accounts)
    if enforce_package_limits:
        counts = export_record_counts(profile, user_ids,
                                      include_unreferenced_accounts=include_unreferenced_accounts)
        total, limit = sum(counts.values()), record_limit()
        if total > limit:
            raise RecordLimitError(total, limit)
    records = {}
    if profile == "application":
        for name, (model, fields) in RESOURCE_FIELDS.items():
            records[name] = json_value(list(model.objects.order_by(model._meta.pk.name).values(*fields)))
    accounts = []
    for user in users.prefetch_related("product_grants", "groups"):
        accounts.append({
            "key": str(user.pk), "username": user.username, "first_name": user.first_name,
            "last_name": user.last_name, "email": user.email, "date_joined": json_value(user.date_joined),
            "grants": sorted(grant.product_ident for grant in user.product_grants.all()),
            "roles": sorted(group.name for group in user.groups.all()),
        })
    if semantic_contract:
        from .compatibility import CURRENT_CONTRACT_VERSION, model_contract
        contract = model_contract(profile)
    else:
        contract = schema_fingerprint()
    payload = {"format": FORMAT_VERSION, "profile": profile, "contract": contract,
               "created_at": json_value(timezone.now()), "selection": {"user_ids": [int(row["key"]) for row in accounts]},
               "accounts": accounts, "records": records}
    if profile == "application":
        from .provenance import export_provenance
        provenance = export_provenance(payload)
        if provenance is not None:
            payload.update(format=RECORD_FORMAT_WITH_PROVENANCE, provenance=provenance)
    if semantic_contract:
        payload.update(format=RECORD_FORMAT_WITH_COMPATIBILITY,
                       contract_version=CURRENT_CONTRACT_VERSION)
    return validate_records(payload, enforce_package_limits=enforce_package_limits)


def snapshot_current_application():
    """Read and validate the current ORM graph without portable package limits.

    This accepts no uploaded records or selection. Native database activation
    uses it inside its snapshot barrier to validate the installed application,
    independently of the size allowed for a portable interchange package.
    The graph is materialized in memory; native SQL inventory streams separately.
    """
    return export_records("application", enforce_package_limits=False)


def _validated_field(field, value, label):
    if value is None:
        if not field.null:
            raise TransferError(f"{label} cannot be null.")
        return None
    target = field.target_field if field.is_relation else field
    kind = target.get_internal_type()
    if kind == "BooleanField":
        valid = type(value) is bool
    elif kind in {"AutoField", "BigAutoField", "SmallAutoField", "IntegerField", "BigIntegerField", "SmallIntegerField", "PositiveIntegerField", "PositiveSmallIntegerField", "PositiveBigIntegerField"}:
        valid = type(value) is int
        if valid and (target.primary_key or kind.startswith("Positive")) and value < (1 if target.primary_key else 0):
            valid = False
    elif kind == "UUIDField":
        require_uuid(value, label)
        valid = True
    elif kind == "DateTimeField":
        require_timestamp(value, label)
        valid = True
    elif kind == "JSONField":
        canonical_bytes(value)
        valid = True
    else:
        valid = isinstance(value, str)
    if not valid:
        raise TransferError(f"{label} has an invalid value type.")
    try:
        converted = target.to_python(value)
        # Blank historical strings remain valid where SQL/domain permits them;
        # validators still enforce lengths, choices and canonical numeric bounds.
        target.run_validators(converted)
        if target.choices and value not in dict(target.flatchoices):
            raise ValidationError("Unsupported choice.")
    except (ValidationError, TypeError, ValueError) as error:
        raise TransferError(f"{label} violates its field contract.") from error
    return converted


def validate_records(payload, *, enforce_package_limits=True):
    """Validate types, complete FK closure and domain identity without writes."""
    _assert_contract_registry()
    if (not isinstance(payload, dict) or type(payload.get("format")) is not int
            or payload["format"] not in SUPPORTED_RECORD_FORMATS):
        raise TransferError("Unsupported record document version.")
    if payload["format"] == RECORD_FORMAT_WITH_COMPATIBILITY:
        keys = (*PAYLOAD_FIELDS, "contract_version")
        if "provenance" in payload:
            keys = (*keys, "provenance")
    else:
        keys = PROVENANCE_PAYLOAD_FIELDS if payload["format"] == RECORD_FORMAT_WITH_PROVENANCE else PAYLOAD_FIELDS
    require_keys(payload, keys, "Record document")
    if not isinstance(payload["profile"], str) or payload["profile"] not in {"accounts", "application"}:
        raise TransferError("Unsupported record transfer profile.")
    if payload["format"] == RECORD_FORMAT_WITH_COMPATIBILITY:
        from .compatibility import validate_record_contract
        validate_record_contract(payload)
    elif payload["contract"] != schema_fingerprint():
        raise TransferError("The package model contract differs from this installation. A reviewed compatible reader is required.")
    require_timestamp(payload["created_at"], "Record creation time")
    require_keys(payload["selection"], ("user_ids",), "Selection")
    accounts = payload["accounts"]
    records = payload["records"]
    if not isinstance(accounts, list) or not isinstance(records, dict):
        raise TransferError("Accounts and resources must be record collections.")
    expected_resources = set(RESOURCE_FIELDS) if payload["profile"] == "application" else set()
    if set(records) != expected_resources:
        raise TransferError("The profile must contain its complete supported resource graph.")
    total = len(accounts) + sum(len(rows) if isinstance(rows, list) else 0 for rows in records.values())
    if enforce_package_limits and total > record_limit():
        raise RecordLimitError(total, record_limit())
    account_keys, usernames = set(), set()
    User = get_user_model()
    for index, row in enumerate(accounts):
        require_keys(row, ACCOUNT_FIELDS, f"Account {index + 1}")
        key = row["key"]
        if not isinstance(key, str) or not key.isascii() or not key.isdecimal() or int(key) <= 0 or str(int(key)) != key or key in account_keys:
            raise TransferError("Source account keys must be unique positive integer strings.")
        account_keys.add(key)
        for name in ("username", "first_name", "last_name", "email", "date_joined"):
            _validated_field(User._meta.get_field(name), row[name], f"Account {key}: {name}")
        if not row["username"] or row["username"] in usernames:
            raise TransferError("Source account usernames must be nonempty and unique.")
        usernames.add(row["username"])
        for name in ("grants", "roles"):
            values = row[name]
            if not isinstance(values, list) or any(not isinstance(value, str) or not value or len(value) > (64 if name == "grants" else 150) for value in values) or len(values) != len(set(values)):
                raise TransferError(f"Account {key}: invalid {name} proposal.")
        if any(normalize_product_ident(value) != value for value in row["grants"]):
            raise TransferError(f"Account {key}: product grants must use canonical identifiers.")
    user_selection = payload["selection"]["user_ids"]
    if not isinstance(user_selection, list) or any(type(value) is not int for value in user_selection) or set(map(str, user_selection)) != account_keys or len(user_selection) != len(account_keys):
        raise TransferError("Account selection does not match the record inventory.")
    identities = {}
    for name, rows in records.items():
        if not isinstance(rows, list):
            raise TransferError(f"{name} must be a record list.")
        model, fields = RESOURCE_FIELDS[name]
        model_fields = {field.attname: field for field in model._meta.concrete_fields}
        keys = set()
        for row in rows:
            require_keys(row, fields, name)
            for field_name in fields:
                field = model_fields[field_name]
                _validated_field(field, row[field_name], f"{name}.{field_name}")
            key = str(row[model._meta.pk.attname])
            if key in keys:
                raise TransferError(f"Duplicate {name} identity.")
            keys.add(key)
        identities[model] = keys
    identities[User] = account_keys
    for name, rows in records.items():
        model, fields = RESOURCE_FIELDS[name]
        for row in rows:
            for field in model._meta.concrete_fields:
                if not field.is_relation or field.attname not in fields or row[field.attname] is None:
                    continue
                if str(row[field.attname]) not in identities.get(field.remote_field.model, set()):
                    raise TransferError(f"{name}.{field.attname} has a missing dependency.")
    if payload["profile"] == "application":
        _validate_unique_keys(records)
        _validate_business_graph(records)
    if payload["format"] == RECORD_FORMAT_WITH_PROVENANCE or "provenance" in payload:
        from .provenance import validate_provenance
        validate_provenance(payload, enforce_package_limits=enforce_package_limits)
    # Reject non-JSON wrappers and return independent, JSON-safe owned values.
    return json_value(payload)


def _by(rows, key):
    return {str(row[key]): row for row in rows}


def _validate_unique_keys(records):
    rules = {
        "products": (("ident",),),
        "definitions": (("product_ident", "digest"),),
        "releases": (("release_key", "revision"),),
        "release_definitions": (("product_release_id", "qc_definition_id"),),
        "units": (("product_release_id", "product_unit_code"),),
        "submissions": (("delivery_id",), ("job_id",)),
        "conflicts": (("product_unit_id",),),
        "conflict_events": (("conflict_id", "version", "event_type"),),
        "review_events": (("submission_id", "version"),),
    }
    for name, keys in rules.items():
        for fields in keys:
            values = [tuple(row[field] for field in fields) for row in records[name]]
            if len(values) != len(set(values)):
                raise TransferError(f"{name} contains conflicting unique record identities.")
    for name, key, condition in (
        ("releases", "release_key", lambda row: row["is_current"]),
        ("releases", "supersedes_id", lambda row: row["supersedes_id"] is not None),
        ("release_definitions", "product_release_id", lambda row: row["is_primary"]),
    ):
        values = [row[key] for row in records[name] if condition(row)]
        if len(values) != len(set(values)):
            raise TransferError(f"{name} contains conflicting current/primary revision identities.")


def _validate_business_graph(records):
    products = _by(records["products"], "id")
    releases = _by(records["releases"], "id")
    definitions = _by(records["definitions"], "id")
    units = _by(records["units"], "id")
    deliveries = _by(records["deliveries"], "id")
    jobs = _by(records["jobs"], "job_uuid")
    submissions = _by(records["submissions"], "submission_uuid")
    conflicts = _by(records["conflicts"], "id")
    links = {(str(row["product_release_id"]), str(row["qc_definition_id"])) for row in records["release_definitions"]}
    for row in records["products"]:
        if normalize_product_ident(row["ident"]) != row["ident"] or not row["name"]:
            raise TransferError("Products must have canonical identifiers and names.")
        if row["ready_at"] and (not row["is_active"] or not SHA256.fullmatch(row["ready_scope_digest"])):
            raise TransferError("Product readiness has incomplete evidence.")
    for row in records["definitions"]:
        if normalize_product_ident(row["product_ident"]) != row["product_ident"] or not SHA256.fullmatch(row["digest"]) or not isinstance(row["document"], dict):
            raise TransferError("Definitions require canonical identities, document objects and original-byte digests.")
    for row in records["releases"]:
        if row["revision"] <= 0 or not row["release_key"] or not SHA256.fullmatch(row["catalog_digest"]):
            raise TransferError("Release revision identity is incomplete.")
        if row["coverage_state"] == "authoritative" and not row["approved_at"]:
            raise TransferError("Authoritative releases require their approval timestamp.")
        previous = row["supersedes_id"]
        if previous is not None:
            parent = releases[str(previous)]
            # Strictly increasing revisions make self-links and longer cycles
            # impossible, with linear validation even for a long revision chain.
            if parent["product_id"] != row["product_id"] or parent["release_key"] != row["release_key"] or parent["revision"] >= row["revision"]:
                raise TransferError("Release supersession must retain its product/stream and increase revision.")
    for row in records["units"]:
        if normalize_product_unit_code(row["product_unit_code"]) != row["product_unit_code"]:
            raise TransferError("Product unit codes must be canonical.")
    for row in records["deliveries"]:
        if row["size_bytes"] < 0 or not row["filename"]:
            raise TransferError("Delivery identity or size is invalid.")
        for name in ("content_sha256",):
            if row[name] and not SHA256.fullmatch(row[name]):
                raise TransferError("Delivery checksums must be SHA-256 values.")
    for row in records["jobs"]:
        if row["job_status"] not in FINAL_JOB_STATUSES:
            raise TransferError("Active or unknown QC jobs cannot be transferred; establish maintenance readiness first.")
        if row["input_sha256"] and not SHA256.fullmatch(row["input_sha256"]):
            raise TransferError("Job input checksums must be SHA-256 values.")
        release_id, definition_id = row["product_release_id"], row["qc_definition_id"]
        if release_id is not None and definition_id is not None:
            definition = definitions[str(definition_id)]
            if (str(release_id), str(definition_id)) not in links or definition["product_ident"] != row["product_ident"]:
                raise TransferError("A job's definition is not linked to its recorded release.")
    accepted = Counter()
    for row in records["submissions"]:
        if row["publication_state"] not in {"published", "failed"}:
            raise TransferError("Incomplete publication cannot be transferred; finish or fail it before export.")
        unit, job = units[str(row["product_unit_id"])], jobs[row["job_id"]]
        delivery = deliveries[str(row["delivery_id"])]
        if unit["product_release_id"] != row["product_release_id"] or row["product_unit_code"] != unit["product_unit_code"] or job["delivery_id"] != row["delivery_id"]:
            raise TransferError("Submission delivery, job, release and unit identities are inconsistent.")
        if job["product_release_id"] != row["product_release_id"] or row["verified_product_unit_code"] != row["product_unit_code"]:
            raise TransferError("Submission release or verified unit differs from its authorizing job/catalog.")
        if row["artifact_key"]:
            from qc_tool.frontend.dashboard.domain.submissions.artifact_keys import validate_artifact_key
            try:
                validate_artifact_key(row["artifact_key"])
            except ValueError as error:
                raise TransferError("Submission artifact key is unsafe.") from error
        if row["publication_state"] == "published":
            if not row["published_at"] or any(not SHA256.fullmatch(row[key]) for key in ("artifact_digest", "input_digest")):
                raise TransferError("Published receipt evidence is incomplete.")
            if job["job_status"] != JOB_OK or row["input_digest"] != job["input_sha256"] or not delivery["date_submitted"]:
                raise TransferError("Published receipt does not match its successful submitted input.")
            if row["review_state"] == "accepted":
                accepted[row["product_unit_id"]] += 1
    if any(count > 1 for count in accepted.values()):
        raise TransferError("A product unit cannot have multiple accepted published submissions.")
    for row in records["conflicts"]:
        selected = row["selected_submission_id"]
        if selected is not None:
            submission = submissions[selected]
            if submission["product_unit_id"] != row["product_unit_id"] or submission["publication_state"] != "published":
                raise TransferError("Conflict selection is outside its published product-unit candidates.")
        if row["state"] == "open":
            valid = selected is None and row["resolved_at"] is None
        elif row["state"] == "resolved":
            valid = selected is not None and row["resolved_at"] is not None
        else:
            valid = selected is None and row["resolved_at"] is not None
        if not valid or row["version"] <= 0:
            raise TransferError("Conflict state, selection, version and resolution disagree.")
    for row in records["conflict_events"]:
        conflict = conflicts[str(row["conflict_id"])]
        if row["version"] <= 0 or row["version"] > conflict["version"]:
            raise TransferError("Conflict event version is outside its retained history.")
        if row["selected_submission_id"] is not None and submissions[row["selected_submission_id"]]["product_unit_id"] != conflict["product_unit_id"]:
            raise TransferError("Conflict event selected a submission for another product unit.")
    for row in records["review_events"]:
        submission = submissions[row["submission_id"]]
        if row["version"] <= 0 or row["version"] > submission["review_version"] or (row["decision"] == "declined" and not row["notes"].strip()):
            raise TransferError("Review event version or required decision evidence is invalid.")


def _target_fingerprint(*, accounts_digest=None):
    User = get_user_model()
    users = ({"evidence": accounts_digest} if accounts_digest is not None else
             list(User.objects.order_by("pk").values("pk", "username", "email", "first_name", "last_name", "is_active", "is_staff", "is_superuser", "password", "date_joined")))
    # Hash credentials to notice a changed target without returning or logging them.
    counts = {name: model.objects.count() for name, (model, _fields) in RESOURCE_FIELDS.items()}
    # A cloned database can contain exactly the same accounts/counts. Bind the
    # review to its configured destination and active schema as well; changing
    # a deployment's database must require a fresh review before publication.
    # Do not include passwords, raw DSNs or arbitrary connection options.
    target = {name.lower(): str(connection.settings_dict.get(name) or "")
              for name in ("NAME", "HOST", "PORT")}
    target["vendor"] = connection.vendor
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_schema()")
            target["database"], target["schema"] = cursor.fetchone()
    return digest({"users": users, "business_counts": counts, "contract": schema_fingerprint(), "target": target})


def plan_records(payload, mappings=None, resolutions=None, *, account_choices=None):
    """Plan reviewed users or an insert-only merge into the application."""
    if isinstance(payload, dict) and payload.get("profile") == "application":
        if account_choices is not None:
            raise TransferError("User selection and profile replacement apply only to user-account packages.")
        from .merge import plan_merge
        return plan_merge(payload, mappings, resolutions)
    if resolutions:
        raise TransferError("Record conflict choices apply only to application imports.")
    if isinstance(payload, dict) and payload.get("profile") == "accounts":
        from .account_import import plan_accounts
        return plan_accounts(payload, mappings, account_choices)
    return _plan_legacy_records(payload, mappings)


def _plan_legacy_records(payload, mappings=None, *, _allow_occupied=False):
    """Read-only preview. Mapping keys are source keys; values are target IDs."""
    payload = validate_records(payload)
    mappings = {} if mappings is None else mappings
    source_keys = {row["key"] for row in payload["accounts"]}
    if not isinstance(mappings, dict) or any(key not in source_keys or type(value) is not int or value <= 0 for key, value in mappings.items()):
        raise TransferError("Account mappings must explicitly name source keys and valid target account IDs.")
    User = get_user_model()
    targets = {user.pk: user for user in User.objects.filter(pk__in=mappings.values())}
    if len(set(mappings.values())) != len(mappings):
        raise TransferError("Map each source account to a distinct destination account.")
    blockers, plans = [], []
    for row in payload["accounts"]:
        target_id = mappings.get(row["key"])
        action = "create"
        if target_id is not None:
            action = "map" if target_id in targets else "blocked"
            if action == "blocked":
                blockers.append(f"Account {row['username']}: mapped destination no longer exists.")
            elif payload["profile"] == "application" and targets[target_id].username != row["username"]:
                action = "blocked"
                blockers.append(f"Account {row['username']}: application restore must preserve usernames because retained upload paths use them.")
        elif User.objects.filter(username__iexact=row["username"]).exists():
            action = "blocked"
            blockers.append(f"Account {row['username']}: username already exists; explicitly map its target identity.")
        plans.append({"source_key": row["key"], "username": row["username"], "action": action, "target_user_id": target_id,
                      "grant_proposals": row["grants"], "role_proposals": row["roles"]})
    if payload["profile"] == "application" and not _allow_occupied:
        occupied = [name for name, (model, _fields) in RESOURCE_FIELDS.items() if model.objects.exists()]
        if occupied:
            blockers.append("Application restore requires empty QC business tables: " + ", ".join(occupied) + ". Existing accounts may be explicitly mapped.")
    return {"profile": payload["profile"], "package_digest": digest(payload), "target_fingerprint": _target_fingerprint(),
            "mappings": mappings, "accounts": plans, "blockers": blockers,
            "counts": {"accounts": len(payload["accounts"]), **{key: len(value) for key, value in payload["records"].items()}},
            "exclusions": ["Passwords and credentials", "Sessions and framework identities", "Automatic roles/product grants", "Remote-source credentials and worker URLs"]}


def apply_records(payload, plan, actor=None):
    """Insert a validated graph atomically, with no side effects or schema changes.

    The caller owns a maintenance pin and file publication. We repeat target and
    package checks inside the caller's transaction. No existing business record
    is ever repaired, overwritten or deleted.
    """
    if plan.get("mode") == "accounts":
        from .account_import import apply_accounts
        return apply_accounts(payload, plan, actor)
    if plan.get("mode") == "additive":
        from .merge import apply_merge
        return apply_merge(payload, plan, actor)
    if not connection.in_atomic_block:
        raise TransferError("Record application requires the coordinated import transaction.")
    current = plan_records(payload, plan.get("mappings"))
    if current != plan:
        raise TransferError("The reviewed import plan is stale. Validate the package and target again.")
    if current["blockers"]:
        raise TransferError("The import plan still contains blockers.")
    payload = validate_records(payload)
    User = get_user_model()
    user_map, created, created_account_keys = {}, Counter(), []
    for row, proposed in zip(payload["accounts"], plan["accounts"]):
        if proposed["action"] == "map":
            user_map[row["key"]] = User.objects.select_for_update().get(pk=proposed["target_user_id"]).pk
            continue
        user = User(username=row["username"], first_name=row["first_name"], last_name=row["last_name"],
                    email=row["email"], date_joined=require_timestamp(row["date_joined"], "Account date"),
                    is_active=False, is_staff=False, is_superuser=False)
        user.set_unusable_password()
        user.full_clean()
        user.save(force_insert=True)
        user_map[row["key"]] = user.pk
        created["accounts"] += 1
        created_account_keys.append(row["key"])
    for name, (model, fields) in RESOURCE_FIELDS.items():
        rows = payload["records"].get(name, [])
        if name == "releases":
            rows = sorted(rows, key=lambda row: (row["revision"], row["id"]))
        for row in rows:
            values = {}
            for field_name in fields:
                field = next(field for field in model._meta.concrete_fields if field.attname == field_name)
                value = row[field_name]
                if field.is_relation and field.remote_field.model is User and value is not None:
                    value = user_map[str(value)]
                values[field_name] = _validated_field(field, value, f"{name}.{field_name}")
            if model is S3Info:
                values["credential_ref"] = ""
            if model is Job:
                values["worker_url"] = None
            instance = model(**values)
            # Run domain clean/constraints with parents already present. Historical
            # blank descriptions are permitted by the stored SQL contract.
            instance.clean()
            instance.validate_unique()
            instance.validate_constraints()
            # raw INSERT preserves immutable source timestamps/explicit PKs and
            # suppresses normal signal/save workflow side effects. Empty-target
            # preconditions and complete validation prohibit bypassing updates.
            instance.save_base(raw=True, force_insert=True)
            created[name] += 1
    # Advance PostgreSQL sequences without moving an existing counter backwards.
    # nextval reserves one identity; sequence gaps on rollback are harmless.
    # SQLite AUTOINCREMENT already observes explicitly inserted maxima.
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            for name, (model, _fields) in RESOURCE_FIELDS.items():
                primary = model._meta.pk
                if not created[name] or primary.get_internal_type() not in {"AutoField", "BigAutoField", "SmallAutoField"}:
                    continue
                table, column = connection.ops.quote_name(model._meta.db_table), connection.ops.quote_name(primary.column)
                cursor.execute(
                    f"SELECT setval(pg_get_serial_sequence(%s, %s), "
                    f"GREATEST(COALESCE((SELECT MAX({column}) FROM {table}), 1), "
                    "nextval(pg_get_serial_sequence(%s, %s))), true)",
                    [model._meta.db_table, primary.column, model._meta.db_table, primary.column],
                )
    connection.check_constraints()
    return {"created_counts": dict(created), "user_mappings": user_map,
            "created_account_keys": created_account_keys}


def verify_records(payload, result):
    """Read-only reconciliation of a committed receipt and its target graph.

    A durable receipt proves atomic commit, rather than continued integrity.
    Recovery checks the retained graph before reopening write admission.
    """
    if result.get("mode") == "accounts":
        from .account_import import verify_accounts
        return verify_accounts(payload, result)
    if result.get("mode") == "additive":
        from .merge import verify_merge
        return verify_merge(payload, result)
    payload = validate_records(payload)
    require_keys(result, ("created_counts", "user_mappings", "created_account_keys"), "Committed import summary")
    mappings, created_keys = result["user_mappings"], result["created_account_keys"]
    source_keys = {row["key"] for row in payload["accounts"]}
    if (not isinstance(mappings, dict) or set(mappings) != source_keys
            or any(type(value) is not int or value <= 0 for value in mappings.values())
            or len(set(mappings.values())) != len(mappings)
            or not isinstance(created_keys, list) or any(not isinstance(key, str) or key not in source_keys for key in created_keys)
            or len(created_keys) != len(set(created_keys))):
        raise TransferError("Committed account identity evidence is incomplete or inconsistent.")
    User = get_user_model()
    users = {user.pk: user for user in User.objects.filter(pk__in=mappings.values()).prefetch_related("groups", "user_permissions", "product_grants")}
    if set(users) != set(mappings.values()):
        raise TransferError("An imported or mapped target account is missing.")
    from qc_tool.frontend.accounts.authorization.roles import Role
    for source in payload["accounts"]:
        user = users[mappings[source["key"]]]
        if payload["profile"] == "application" and user.username != source["username"]:
            raise TransferError("An application account identity no longer matches its retained upload paths.")
        if source["key"] not in created_keys:
            continue
        if (user.is_active or user.is_staff or user.is_superuser or user.has_usable_password()
                or user.user_permissions.exists() or user.product_grants.exists()
                or set(group.name for group in user.groups.all()) != {Role.DEFAULT.value}):
            raise TransferError("An imported account's inactive access boundary has changed.")
        if any(json_value(getattr(user, name)) != source[name] for name in ("username", "first_name", "last_name", "email", "date_joined")):
            raise TransferError("An imported account differs from its committed source profile.")
    expected_counts = {"accounts": len(created_keys)} if created_keys else {}
    if payload["profile"] == "application":
        for name, (model, fields) in RESOURCE_FIELDS.items():
            expected = []
            for source in payload["records"][name]:
                row = dict(source)
                for field in model._meta.concrete_fields:
                    if field.is_relation and field.remote_field.model is User and row.get(field.attname) is not None:
                        row[field.attname] = mappings[str(row[field.attname])]
                expected.append(row)
            actual = json_value(list(model.objects.values(*fields)))
            key = model._meta.pk.attname
            if sorted(expected, key=lambda row: str(row[key])) != sorted(actual, key=lambda row: str(row[key])):
                raise TransferError(f"Committed {name} records differ from the imported graph; keep maintenance enabled and investigate.")
            if expected:
                expected_counts[name] = len(expected)
        if S3Info.objects.exclude(credential_ref="").exists() or Job.objects.exclude(worker_url__isnull=True).exists():
            raise TransferError("Imported remote credentials or worker bindings have changed before verification.")
    if result["created_counts"] != expected_counts:
        raise TransferError("Committed record counts differ from the verified import graph.")
    return {"verified_counts": expected_counts, "records_digest": digest(payload["records"])}
