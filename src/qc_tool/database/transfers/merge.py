"""Dependency-aware, insert-only application transfers.

The reviewed plan owns every identity translation. Existing rows are never
updated, including when an administrator explicitly reuses a catalog identity.
The receipt is the durable provenance record, committed with the new graph.
"""

from collections import Counter, defaultdict, deque
import hashlib
from functools import partial
from uuid import NAMESPACE_URL, uuid5

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.db.models import Max

from .contracts import TransferError, canonical_bytes, digest, json_value, require_timestamp


# Identity lookup is deliberately explicit. A numeric source PK is never a
# candidate target PK unless a previously committed provenance map says so.
NATURAL_KEYS = {
    "products": ("ident",), "definitions": ("product_ident", "digest"),
    "releases": ("release_key", "revision"),
    "release_definitions": ("product_release_id", "qc_definition_id"),
    "units": ("product_release_id", "product_unit_code"),
    "jobs": ("job_uuid",), "submissions": ("submission_uuid",),
    "conflicts": ("product_unit_id",),
    "conflict_events": ("conflict_id", "version", "event_type"),
    "review_events": ("submission_id", "version"),
}

# Operator-selectable reuse applies only when immutable catalog content agrees.
# Local activation/readiness/approval and descriptive differences are retained
# in the source audit, while the current destination record stays untouched.
REUSE_CORE = {
    "products": ("ident",),
    "definitions": ("product_ident", "digest", "description", "document"),
    "releases": ("product_id", "release_key", "revision", "description", "catalog_digest", "source_kind", "coverage_state", "supersedes_id"),
    "units": ("product_release_id", "product_unit_code", "source_value", "provenance"),
}
MAX_TARGET_SNAPSHOT_ROWS = 1_000_000
SNAPSHOT_CHUNK_SIZE = 1_000


def _registry():
    from .records import RESOURCE_FIELDS
    return RESOURCE_FIELDS


def _snapshot():
    """Stream private per-row evidence without materializing target contents."""
    User = get_user_model()
    visited = 0

    def rows(model, *, owner_field=None):
        nonlocal visited
        ordering = (owner_field, model._meta.pk.attname) if owner_field else (model._meta.pk.attname,)
        for row in model.objects.order_by(*ordering).values().iterator(chunk_size=SNAPSHOT_CHUNK_SIZE):
            visited += 1
            if visited > MAX_TARGET_SNAPSHOT_ROWS:
                raise TransferError(
                    f"This destination exceeds the {MAX_TARGET_SNAPSHOT_ROWS} row additive verification limit. "
                    "Use a full database backup or a reviewed offline transfer for this dataset."
                )
            yield row

    def row_evidence(model):
        key = model._meta.pk.attname
        return {str(row[key]): digest(row) for row in rows(model)}

    def access_evidence(model, *, owner_field="user_id"):
        # Grouped digests detect added authority as well as edits/removals,
        # while new imported accounts can receive their separate default role.
        evidence, owner, checksum = {}, None, None
        for row in rows(model, owner_field=owner_field):
            current_owner = str(row[owner_field])
            if current_owner != owner:
                if owner is not None:
                    evidence[owner] = checksum.hexdigest()
                owner, checksum = current_owner, hashlib.sha256()
            checksum.update(canonical_bytes(row))
            checksum.update(b"\n")
        if owner is not None:
            evidence[owner] = checksum.hexdigest()
        return evidence

    evidence = {"users": row_evidence(User), "records": {}, "access": {}}
    for name, (model, fields) in _registry().items():
        # Include excluded live credentials/bindings in the private baseline.
        evidence["records"][name] = row_evidence(model)
    for name, relation in (("groups", User.groups.through), ("permissions", User.user_permissions.through)):
        evidence["access"][name] = access_evidence(relation)
    from qc_tool.frontend.accounts.models import UserProductGrant
    evidence["access"]["product_grants"] = access_evidence(UserProductGrant)
    evidence["authority"] = {
        "groups": row_evidence(Group), "permissions": row_evidence(Permission),
        "content_types": row_evidence(ContentType),
        "group_permissions": access_evidence(Group.permissions.through, owner_field="group_id"),
    }
    return evidence


def _fingerprint():
    from .records import _target_fingerprint
    return digest({"identity": _target_fingerprint(), "values": _snapshot()})


def _origins(payload):
    provenance = payload.get("provenance")
    if provenance:
        return provenance["identities"]
    # V1 did not identify its installation. Identical legacy graphs can be
    # retried safely; a changed legacy graph is a new source. New exports use V2.
    namespace = str(uuid5(NAMESPACE_URL, "qc-tool-v1:" + digest({
        key: payload[key] for key in ("contract", "accounts", "records")
    })))
    return {"accounts": {row["key"]: {"namespace": namespace, "key": row["key"]}
                         for row in payload["accounts"]}, **{
        name: {str(row[model._meta.pk.attname]): {"namespace": namespace, "key": str(row[model._meta.pk.attname])}
               for row in payload["records"][name]}
        for name, (model, _fields) in _registry().items()
    }}


def _dependencies(name, row):
    registry = _registry()
    resources = {model: resource for resource, (model, _fields) in registry.items()}
    resources[get_user_model()] = "accounts"
    model, fields = registry[name]
    return [(resources[field.remote_field.model], str(row[field.attname]))
            for field in model._meta.concrete_fields
            if field.is_relation and field.attname in fields and row[field.attname] is not None]


def _dependent_index(payload):
    records = payload["records"]
    products = {row["ident"]: str(row["id"]) for row in records["products"]}
    links = {(row["product_release_id"], row["qc_definition_id"]): str(row["id"]) for row in records["release_definitions"]}
    dependents = defaultdict(set)
    for name, (model, _fields) in _registry().items():
        for row in records[name]:
            key = (name, str(row[model._meta.pk.attname]))
            for dependency in _dependencies(name, row):
                dependents[dependency].add(key)
            if name in {"definitions", "deliveries", "jobs"} and row.get("product_ident") in products:
                dependents[("products", products[row["product_ident"]])].add(key)
            if name == "jobs":
                link = links.get((row["product_release_id"], row["qc_definition_id"]))
                if link:
                    dependents[("release_definitions", link)].add(key)
            # A partial event history cannot represent its parent's decision.
            if name == "review_events":
                dependents[key].add(("submissions", str(row["submission_id"])))
            if name == "conflict_events":
                dependents[key].add(("conflicts", str(row["conflict_id"])))
    return dependents


def _skip_closure(payload, initial, *, dependents=None):
    dependents = _dependent_index(payload) if dependents is None else dependents
    skipped, pending = set(initial), deque(initial)
    while pending:
        for child in dependents.get(pending.popleft(), ()):
            if child not in skipped:
                skipped.add(child)
                pending.append(child)
    return skipped


def _translate(name, source, identities):
    model, fields = _registry()[name]
    resources = {model: resource for resource, (model, _fields) in _registry().items()}
    resources[get_user_model()] = "accounts"
    row = dict(source)
    row[model._meta.pk.attname] = identities[name][str(source[model._meta.pk.attname])]
    for field in model._meta.concrete_fields:
        if field.is_relation and field.attname in fields and row[field.attname] is not None:
            row[field.attname] = identities[resources[field.remote_field.model]][str(row[field.attname])]
    return row


def _conflict(payload, name, source, reason, differences=(), *, reuse=False, resolution=None, dependents=None):
    model = _registry()[name][0]
    source_key = str(source[model._meta.pk.attname])
    impact = Counter(resource for resource, _key in _skip_closure(payload, {(name, source_key)}, dependents=dependents))
    choices = [{"value": "skip", "label": "Skip incoming record and dependent history"}]
    if reuse:
        choices.insert(0, {"value": "reuse", "label": "Use existing record without changing it"})
    return {"key": f"{name}:{source_key}", "resource": name,
            "label": str(source.get("filename") or source.get("ident") or source.get("release_key") or source_key),
            "reason": reason, "differences": list(differences), "choices": choices,
            "resolution": resolution, "impact": dict(impact)}


def _structural_collision(name, row):
    """Partial unique constraints and domain decisions need explicit handling."""
    from qc_tool.frontend.dashboard.models import DeliverySubmission, ProductRelease, ProductReleaseDefinition
    if name == "releases":
        if row["is_current"] and ProductRelease.objects.filter(release_key=row["release_key"], is_current=True).exists():
            return "The destination already has a current revision for this release."
        if row["supersedes_id"] and ProductRelease.objects.filter(supersedes_id=row["supersedes_id"]).exists():
            return "The destination already has a successor for this release revision."
    if name == "release_definitions" and row["is_primary"] and ProductReleaseDefinition.objects.filter(
            product_release_id=row["product_release_id"], is_primary=True).exists():
        return "The destination already has a primary QC definition for this release."
    if name == "submissions":
        if DeliverySubmission.objects.filter(delivery_id=row["delivery_id"]).exists() or DeliverySubmission.objects.filter(job_id=row["job_id"]).exists():
            return "The destination delivery or job already belongs to another submission."
        if row["publication_state"] == "published" and row["review_state"] == "accepted" and DeliverySubmission.objects.filter(
                product_unit_id=row["product_unit_id"], publication_state="published", review_state="accepted").exists():
            return "This product unit already has an accepted submission. Existing review decisions are preserved."
    return None


def plan_merge(payload, mappings=None, resolutions=None):
    from .records import _plan_legacy_records, validate_records
    from .provenance import load_identity_index
    payload = validate_records(payload)
    base = _plan_legacy_records(payload, mappings, _allow_occupied=True)
    resolutions = {} if resolutions is None else resolutions
    if not isinstance(resolutions, dict) or any(not isinstance(key, str) or not isinstance(value, str) or value not in {"skip", "reuse"} for key, value in resolutions.items()):
        raise TransferError("Choose only the available record conflict decisions.")
    registry, User = _registry(), get_user_model()
    known = {f"{name}:{row[model._meta.pk.attname]}" for name, (model, _fields) in registry.items() for row in payload["records"][name]}
    if set(resolutions) - known:
        raise TransferError("A conflict decision names a record outside this package.")
    origins, prior = _origins(payload), load_identity_index()
    identities = {name: {} for name in ("accounts", *registry)}
    next_user = (User.objects.aggregate(value=Max("pk"))["value"] or 0) + 1
    for account in base["accounts"]:
        key = account["source_key"]
        origin = origins["accounts"][key]
        prior_user = prior.get(("accounts", origin["namespace"], origin["key"]))
        if prior_user is not None and (account["target_user_id"] != prior_user or not User.objects.filter(pk=prior_user).exists()):
            base["blockers"].append(f"Account {account['username']}: this source identity was previously mapped to another account; it cannot be rebound.")
            account["action"] = "blocked"
        identities["accounts"][key] = account["target_user_id"] or next_user
        if account["target_user_id"] is None:
            next_user += 1
    dependents = _dependent_index(payload)
    conflict_for = partial(_conflict, payload, dependents=dependents)
    skipped = _skip_closure(payload, {tuple(key.split(":", 1)) for key, value in resolutions.items() if value == "skip"}, dependents=dependents)
    actions, conflicts, blockers, source_overrides = {}, [], list(base["blockers"]), {}
    pending = {}
    for name, (model, fields) in registry.items():
        actions[name], pending[name] = {}, []
        next_id = ((model.objects.aggregate(value=Max("pk"))["value"] or 0) + 1
                   if model._meta.pk.get_internal_type() in {"AutoField", "BigAutoField", "SmallAutoField"} else None)
        rows = payload["records"][name]
        if name == "releases":
            rows = sorted(rows, key=lambda row: (row["revision"], row["id"]))
        for source in rows:
            source_key = str(source[model._meta.pk.attname])
            decision = resolutions.get(f"{name}:{source_key}")
            if (name, source_key) in skipped:
                actions[name][source_key] = "skip"
                if decision == "skip":
                    conflicts.append(conflict_for(name, source, "Incoming record and its dependent history are excluded.", resolution="skip"))
                continue
            # Parents are visited before their children. An unresolved parent
            # blocks its descendants without fabricating an unrelated match.
            if any(key not in identities[resource] for resource, key in _dependencies(name, source)):
                actions[name][source_key] = "blocked"
                continue
            provisional = next_id if next_id is not None else source[model._meta.pk.attname]
            identities[name][source_key] = provisional
            translated = _translate(name, source, identities)
            origin = origins[name][source_key]
            prior_id = prior.get((name, origin["namespace"], origin["key"]))
            candidate = None
            if prior_id is not None:
                candidate = model.objects.filter(pk=prior_id).first()
                if candidate is None:
                    reason = "A previously imported source identity no longer exists in the destination."
                    actions[name][source_key] = "blocked"
                    identities[name].pop(source_key)
                    conflicts.append(conflict_for(name, source, reason))
                    continue
            elif name in NATURAL_KEYS:
                matches = list(model.objects.filter(**{key: translated[key] for key in NATURAL_KEYS[name]})[:2])
                if len(matches) == 1:
                    candidate = matches[0]
                elif len(matches) > 1:
                    actions[name][source_key] = "blocked"
                    identities[name].pop(source_key)
                    conflicts.append(conflict_for(name, source, "More than one destination record matches this logical identity."))
                    continue
            if candidate is not None:
                identities[name][source_key] = json_value(candidate.pk)
                translated = _translate(name, source, identities)
                actual = json_value({field: getattr(candidate, field) for field in fields})
                differences = [{"field": field, "current": actual[field], "incoming": translated[field]}
                               for field in fields if actual[field] != translated[field]]
                # Product identity is stable while its presentation/readiness
                # is local operational state. Reuse requires explicit consent
                # when any value differs. Other immutable history is exact.
                can_reuse = name in REUSE_CORE and all(actual[field] == translated[field] for field in REUSE_CORE[name])
                if differences:
                    conflict = conflict_for(name, source,
                        "The same logical identity has different values. Existing records will stay unchanged.",
                        differences, reuse=can_reuse, resolution=decision)
                    conflicts.append(conflict)
                    if decision != "reuse" or not can_reuse:
                        actions[name][source_key] = "blocked"
                        identities[name].pop(source_key)
                        continue
                    source_overrides.setdefault(name, {})[source_key] = source
                elif decision == "reuse":
                    # A former conflict may now be exact. Reuse remains safe.
                    pass
                actions[name][source_key] = "reuse"
                continue
            collision = _structural_collision(name, translated)
            if collision or decision == "reuse":
                actions[name][source_key] = "blocked"
                identities[name].pop(source_key)
                conflicts.append(conflict_for(name, source, collision or "There is no compatible destination record to reuse."))
                continue
            # Source readiness cannot authorize a newly allocated local scope.
            if name == "products" and translated["ready_at"] is not None:
                source_overrides.setdefault(name, {})[source_key] = source
                translated.update(ready_at=None, ready_by_id=None, ready_by_username="", ready_scope_digest="")
            actions[name][source_key] = "create"
            pending[name].append(translated)
            if next_id is not None:
                next_id += 1
    for conflict in conflicts:
        if conflict["resolution"] not in {choice["value"] for choice in conflict["choices"]}:
            blockers.append(f"{conflict['resource']}: {conflict['label']} needs a conflict decision.")
    if any(action == "blocked" for rows in actions.values() for action in rows.values()) and not blockers:
        blockers.append("Resolve the incoming records' dependencies before importing.")
    included = {name: [key for key, action in rows.items() if action in {"create", "reuse"}] for name, rows in actions.items()}
    if not blockers:
        from .records import _validate_business_graph, _validate_unique_keys
        included_sets = {name: set(keys) for name, keys in included.items()}
        selected = {name: [row for row in payload["records"][name] if str(row[model._meta.pk.attname]) in included_sets[name]]
                    for name, (model, _fields) in registry.items()}
        try:
            _validate_unique_keys(selected)
            _validate_business_graph(selected)
        except (TransferError, KeyError) as error:
            blockers.append("The selected records do not retain a complete consistent history. Review the excluded dependencies.")
    summary = [{"resource": name, "label": name.replace("_", " ").capitalize(),
                **{action: sum(value == action for value in rows.values()) for action in ("create", "reuse", "skip", "blocked")}}
               for name, rows in actions.items() if rows]
    summary.insert(0, {"resource": "accounts", "label": "User accounts",
                       "create": sum(row["action"] == "create" for row in base["accounts"]),
                       "reuse": sum(row["action"] == "map" for row in base["accounts"]), "skip": 0,
                       "blocked": sum(row["action"] == "blocked" for row in base["accounts"])})
    return {**base, "mode": "additive", "version": 1, "resolutions": dict(resolutions),
            "target_fingerprint": _fingerprint(), "identity_map": identities,
            "origins": origins, "actions": actions, "pending": pending,
            "included": included, "record_conflicts": conflicts, "resource_summary": summary,
            "source_overrides": source_overrides, "blockers": blockers}


def _lock_tables():
    """Stop direct SQL writers too during final validation/insertion on PG."""
    if connection.vendor == "postgresql":
        User = get_user_model()
        from qc_tool.database.models import TransferReceipt
        from qc_tool.frontend.accounts.models import UserProductGrant
        models = [User, User.groups.through, User.user_permissions.through, UserProductGrant, TransferReceipt,
                  Group, Permission, Group.permissions.through, ContentType,
                  *(model for model, _fields in _registry().values())]
        tables = sorted({connection.ops.quote_name(model._meta.db_table) for model in models})
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '5s'")
            cursor.execute("LOCK TABLE " + ", ".join(tables) + " IN SHARE ROW EXCLUSIVE MODE")


def apply_merge(payload, plan, actor=None):
    from .records import _validated_field
    from .provenance import PUBLICATION_FIELDS, get_package_publication_identity
    if not connection.in_atomic_block:
        raise TransferError("Additive import requires the coordinated transaction.")
    _lock_tables()
    current = plan_merge(payload, plan["mappings"], plan["resolutions"])
    if current != plan or current["blockers"]:
        raise TransferError("The reviewed import plan is stale or blocked. Review it again.")
    before = _snapshot()
    User, created, created_keys = get_user_model(), Counter(), []
    for source, proposed in zip(payload["accounts"], plan["accounts"]):
        if proposed["action"] == "map":
            continue
        user = User(pk=plan["identity_map"]["accounts"][source["key"]], username=source["username"],
                    first_name=source["first_name"], last_name=source["last_name"], email=source["email"],
                    date_joined=require_timestamp(source["date_joined"], "Account date"),
                    is_active=False, is_staff=False, is_superuser=False)
        user.set_unusable_password()
        user.full_clean()
        user.save(force_insert=True)
        created["accounts"] += 1
        created_keys.append(source["key"])
    for name, (model, fields) in _registry().items():
        for row in plan["pending"][name]:
            values = {field: _validated_field(next(item for item in model._meta.concrete_fields if item.attname == field),
                                              row[field], f"{name}.{field}") for field in fields}
            if name == "remote_sources":
                values["credential_ref"] = ""
            if name == "jobs":
                values["worker_url"] = None
            instance = model(**values)
            instance.clean()
            instance.validate_unique()
            instance.validate_constraints()
            instance.save_base(raw=True, force_insert=True)
            created[name] += 1
    _advance_sequences(created)
    connection.check_constraints()
    publications = {row["submission_uuid"]: get_package_publication_identity(payload, row)
                    for row in payload["records"]["submissions"]
                    if row["publication_state"] == "published" and str(row["submission_uuid"]) in plan["included"]["submissions"]}
    publication_targets = {row["submission_uuid"]: {key: _translate("submissions", row, plan["identity_map"])[key]
                                                   for key in PUBLICATION_FIELDS}
                           for row in payload["records"]["submissions"] if row["submission_uuid"] in publications}
    source_evidence = []
    for evidence in payload.get("provenance", {}).get("source_records", []):
        target = plan["identity_map"][evidence["resource"]].get(evidence["target_key"])
        if target is not None:
            source_evidence.append({**evidence, "target_key": str(target)})
    baseline = before
    expected = {name: {str(row[model._meta.pk.attname]): row for row in plan["pending"][name]}
                for name, (model, _fields) in _registry().items()}
    return {"mode": "additive", "version": 1, "created_counts": dict(created),
            "user_mappings": plan["identity_map"]["accounts"], "created_account_keys": created_keys,
            "identity_map": plan["identity_map"], "origins": plan["origins"],
            "publication_identities": publications, "publication_targets": publication_targets,
            "source_overrides": plan["source_overrides"], "source_evidence": source_evidence,
            "actions": plan["actions"], "expected": expected, "baseline": baseline,
            "resource_summary": plan["resource_summary"], "records_digest": digest(payload),
            "destination_jobs": list(plan["identity_map"]["jobs"].values())[:100]}


def _advance_sequences(created):
    if connection.vendor != "postgresql":
        return
    models = [("accounts", get_user_model()), *((name, model) for name, (model, _fields) in _registry().items())]
    with connection.cursor() as cursor:
        for name, model in models:
            primary = model._meta.pk
            if not created[name] or primary.get_internal_type() not in {"AutoField", "BigAutoField", "SmallAutoField"}:
                continue
            table, column = connection.ops.quote_name(model._meta.db_table), connection.ops.quote_name(primary.column)
            cursor.execute(f"SELECT setval(pg_get_serial_sequence(%s,%s), GREATEST(COALESCE((SELECT MAX({column}) FROM {table}),1), nextval(pg_get_serial_sequence(%s,%s))),true)",
                           [model._meta.db_table, primary.column, model._meta.db_table, primary.column])


def verify_merge(payload, result):
    """Reconcile only this import's rows and unchanged pre-existing records."""
    from .records import validate_records
    payload = validate_records(payload)
    if result.get("version") != 1 or result.get("records_digest") != digest(payload):
        raise TransferError("The committed additive receipt does not match the package.")
    current = _snapshot()
    for key, expected in result["baseline"]["users"].items():
        if key in current["users"] and current["users"][key] != expected:
            raise TransferError("A pre-existing account changed during additive import.")
    if not set(result["baseline"]["users"]).issubset(current["users"]):
        raise TransferError("A pre-existing account is missing after additive import.")
    access_baseline = result["baseline"].get("access")
    if not isinstance(access_baseline, dict) or set(access_baseline) != set(current["access"]):
        raise TransferError("The committed additive receipt is missing existing account access evidence.")
    existing_users = set(result["baseline"]["users"])
    for name, users in current["access"].items():
        # New accounts legitimately acquire the default role. For every
        # pre-existing account, detect added, removed or edited access rows.
        # Checking only original row IDs would miss newly granted authority.
        retained = {key: checksum for key, checksum in users.items() if key in existing_users}
        if retained != access_baseline[name]:
            raise TransferError("Pre-existing account access changed during additive import.")
    authority_baseline = result["baseline"].get("authority")
    if not isinstance(authority_baseline, dict) or set(authority_baseline) != set(current["authority"]):
        raise TransferError("The committed additive receipt is missing authorization definition evidence.")
    for name in ("groups", "permissions", "content_types"):
        for key, expected in authority_baseline[name].items():
            if current["authority"][name].get(key) != expected:
                raise TransferError("Pre-existing authorization definitions changed during additive import.")
    existing_groups = set(authority_baseline["groups"])
    retained_permissions = {key: checksum for key, checksum in current["authority"]["group_permissions"].items()
                            if key in existing_groups}
    if retained_permissions != authority_baseline["group_permissions"]:
        raise TransferError("Pre-existing group permissions changed during additive import.")
    counts = Counter()
    for name, (model, fields) in _registry().items():
        rows = current["records"][name]
        for key, expected in result["baseline"]["records"][name].items():
            if rows.get(key) != expected:
                raise TransferError(f"Pre-existing {name} records changed during additive import.")
        expected_rows = result["expected"][name]
        keys = list(expected_rows)
        selected_fields = (*fields, *(("worker_url",) if name == "jobs" else
                                     ("credential_ref",) if name == "remote_sources" else ()))
        matched = 0
        for offset in range(0, len(keys), SNAPSHOT_CHUNK_SIZE):
            query = model.objects.filter(pk__in=keys[offset:offset + SNAPSHOT_CHUNK_SIZE]).order_by(model._meta.pk.attname)
            for row in query.values(*selected_fields).iterator(chunk_size=SNAPSHOT_CHUNK_SIZE):
                row = json_value(row)
                key = str(row[model._meta.pk.attname])
                if {field: row[field] for field in fields} != expected_rows[key]:
                    raise TransferError(f"Imported {name} records differ from their receipt.")
                if name == "jobs" and row["worker_url"] is not None:
                    raise TransferError("An imported job unexpectedly has a worker binding.")
                if name == "remote_sources" and row["credential_ref"]:
                    raise TransferError("An imported remote source unexpectedly has credentials.")
                matched += 1
        if matched != len(expected_rows):
            raise TransferError(f"Imported {name} records differ from their receipt.")
        if matched:
            counts[name] = matched
    from qc_tool.frontend.accounts.authorization.roles import Role
    User = get_user_model()
    source_accounts = {row["key"]: row for row in payload["accounts"]}
    for key in result["created_account_keys"]:
        try:
            user = User.objects.get(pk=result["user_mappings"][key])
        except User.DoesNotExist as error:
            raise TransferError("An imported account is missing.") from error
        if (user.is_active or user.is_staff or user.is_superuser or user.has_usable_password()
                or user.user_permissions.exists() or user.product_grants.exists()
                or set(user.groups.values_list("name", flat=True)) != {Role.DEFAULT.value}
                or any(json_value(getattr(user, field)) != source_accounts[key][field]
                       for field in ("username", "first_name", "last_name", "email", "date_joined"))):
            raise TransferError("An imported account differs from its inactive source profile.")
        counts["accounts"] += 1
    if dict(counts) != result["created_counts"]:
        raise TransferError("The committed additive counts do not match its verified rows.")
    return {"verified_counts": dict(counts), "records_digest": result["records_digest"]}
