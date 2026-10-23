"""Reviewed user selections and bounded, in-place profile updates.

Account packages carry identity/profile proposals, never credentials or authority.
Application graph imports retain their independent, insert-only contract.
"""

import hashlib

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.db import connection

from .contracts import TransferError, canonical_bytes, digest, json_value, require_keys, require_timestamp


PROFILE_FIELDS = ("first_name", "last_name", "email")
PROFILE_LABELS = {"first_name": "First name", "last_name": "Last name", "email": "Email"}
ACTIONS = frozenset(("import", "reuse", "replace", "skip"))
MAX_AUTH_ROWS = 1_000_000
RESULT_FIELDS = (
    "mode", "version", "package_digest", "account_choices", "created_counts", "updated_counts",
    "reused_counts", "created_account_keys", "updated_account_keys", "skipped_account_keys",
    "user_mappings", "target_digest",
)


def _auth_models():
    User = get_user_model()
    from qc_tool.frontend.accounts.models import PersonalAccessToken, UserProductGrant
    return (
        (User, None), (User.groups.through, "user_id"), (User.user_permissions.through, "user_id"),
        (UserProductGrant, "user_id"), (PersonalAccessToken, "user_id"),
        (Group, None), (Permission, None), (Group.permissions.through, None),
        (ContentType, None), (Session, None),
    )


def _auth_digest(*, exclude_users=(), profile_updates=()):
    """Stream private evidence; no credential values leave this function."""
    User, checksum, count = get_user_model(), hashlib.sha256(), 0
    excluded, updates = set(exclude_users), set(profile_updates)
    for model, owner in _auth_models():
        queryset = model.objects.order_by(model._meta.pk.attname)
        if excluded and (model is User or owner):
            queryset = queryset.exclude(**{("pk__in" if model is User else owner + "__in"): excluded})
        checksum.update(canonical_bytes(model._meta.label_lower))
        for row in queryset.values().iterator(chunk_size=1000):
            count += 1
            if count > MAX_AUTH_ROWS:
                raise TransferError("This destination exceeds the account verification limit; use a reviewed offline transfer.")
            if model is User and row[model._meta.pk.attname] in updates:
                row = {key: value for key, value in row.items() if key not in PROFILE_FIELDS}
            checksum.update(canonical_bytes(row))
            checksum.update(b"\n")
    return checksum.hexdigest()


def _choices(payload, mappings, choices):
    source_keys = {row["key"] for row in payload["accounts"]}
    mappings = {} if mappings is None else mappings
    choices = {} if choices is None else choices
    if (not isinstance(mappings, dict) or any(key not in source_keys or type(value) is not int or value <= 0
                                             for key, value in mappings.items())):
        raise TransferError("Account mappings must explicitly name source keys and valid target account IDs.")
    if not isinstance(choices, dict) or any(key not in source_keys for key in choices):
        raise TransferError("User choices must name only accounts in the uploaded package.")
    normalized = {}
    for source in payload["accounts"]:
        key = source["key"]
        if key in choices:
            choice = choices[key]
            if (not isinstance(choice, dict) or set(choice) - {"action", "target_id"}
                    or not isinstance(choice.get("action"), str) or choice["action"] not in ACTIONS):
                raise TransferError("Choose import, reuse, replace or skip for each incoming user.")
            action, target = choice["action"], choice.get("target_id")
        else:
            action, target = ("reuse", mappings[key]) if key in mappings else ("import", None)
        if action in {"reuse", "replace"}:
            if type(target) is not int or target <= 0:
                raise TransferError("Reusing or replacing a profile requires an explicit destination user.")
        elif target is not None:
            raise TransferError("Import and skip choices must not name an existing destination user.")
        normalized[key] = {"action": action, "target_id": target}
    targets = [row["target_id"] for row in normalized.values() if row["target_id"] is not None]
    if len(targets) != len(set(targets)):
        raise TransferError("Map each source account to a distinct destination account.")
    return normalized


def plan_accounts(payload, mappings=None, account_choices=None):
    from .records import _target_fingerprint, validate_records
    payload = validate_records(payload)
    if payload["profile"] != "accounts":
        raise TransferError("User selection and profile replacement apply only to user-account packages.")
    choices = _choices(payload, mappings, account_choices)
    names = {row["username"].casefold() for row in payload["accounts"]}
    target_ids = {choice["target_id"] for choice in choices.values() if choice["target_id"] is not None}
    targets, duplicates = {}, {}
    User = get_user_model()
    for user in User.objects.only("pk", "username", *PROFILE_FIELDS).order_by("pk").iterator(chunk_size=1000):
        normalized = user.username.casefold()
        if normalized in names:
            duplicates.setdefault(normalized, []).append(user)
        if user.pk in target_ids:
            targets[user.pk] = user
    plans, blockers, new_names = [], [], set()
    summary = {name: 0 for name in ("selected", "create", "reuse", "replace", "skip", "blocked")}
    for source in payload["accounts"]:
        choice = choices[source["key"]]
        disposition, target_id = choice["action"], choice["target_id"]
        candidates = duplicates.get(source["username"].casefold(), [])
        target = targets.get(target_id)
        action = {"import": "create", "reuse": "map", "replace": "update", "skip": "skip"}[disposition]
        reason = ""
        if disposition in {"reuse", "replace"} and target is None:
            reason = "mapped destination no longer exists."
        elif disposition == "replace" and target.username.casefold() != source["username"].casefold():
            reason = "profile replacement requires a matching username; destination identity is never renamed."
        elif disposition == "import" and candidates:
            reason = "username already exists; explicitly reuse, replace its profile or skip this user."
        elif disposition == "import" and source["username"].casefold() in new_names:
            reason = "another selected incoming user has the same username ignoring case."
        if reason:
            action = "blocked"
            blockers.append(f"Account {source['username']}: {reason}")
        if disposition == "import":
            new_names.add(source["username"].casefold())
        if disposition != "skip":
            summary["selected"] += 1
        summary[{"map": "reuse", "update": "replace"}.get(action, action)] += 1
        comparison = target or (candidates[0] if len(candidates) == 1 else None)
        allowed = []
        if not candidates:
            allowed.append({"value": "import", "label": "Import as a new inactive user"})
        if candidates or target:
            allowed.append({"value": "reuse", "label": "Use existing user without changing it"})
        if candidates:
            allowed.append({"value": "replace", "label": "Replace name and email only"})
        allowed.append({"value": "skip", "label": "Skip incoming user"})
        candidate_rows = [{"id": item.pk, "username": item.username,
                           **{field: getattr(item, field) for field in PROFILE_FIELDS}} for item in candidates]
        if target and target.pk not in {row["id"] for row in candidate_rows}:
            candidate_rows.append({"id": target.pk, "username": target.username,
                                   **{field: getattr(target, field) for field in PROFILE_FIELDS}})
        plans.append({
            "source_key": source["key"], "username": source["username"], "action": action,
            "target_user_id": target_id, "selected": disposition != "skip",
            "disposition": "" if action == "blocked" and disposition == "import" else disposition,
            "choices": allowed, "candidate_targets": candidate_rows,
            "differences": [{"field": PROFILE_LABELS[field], "current": getattr(comparison, field) if comparison else None,
                             "incoming": source[field]} for field in PROFILE_FIELDS],
            "grant_proposals": source["grants"], "role_proposals": source["roles"],
        })
    if not summary["selected"]:
        blockers.append("Select at least one incoming user before importing.")
    summary["total"] = len(plans)
    return {
        "mode": "accounts", "version": 1, "profile": "accounts", "package_digest": digest(payload),
        "target_fingerprint": _target_fingerprint(accounts_digest=_auth_digest()),
        "mappings": {key: row["target_id"] for key, row in choices.items() if row["target_id"] is not None},
        "account_choices": choices, "account_summary": summary, "accounts": plans, "blockers": blockers,
        "counts": {"accounts": summary["selected"]},
        "exclusions": ["Passwords and credentials", "Sessions and framework identities", "Automatic roles/product grants",
                       "Existing usernames, account dates and security flags"],
    }


def _lock_tables():
    if connection.vendor == "postgresql":
        from qc_tool.database.models import TransferReceipt
        tables = sorted({connection.ops.quote_name(model._meta.db_table)
                         for model in [*(model for model, _owner in _auth_models()), TransferReceipt]})
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '5s'")
            cursor.execute("LOCK TABLE " + ", ".join(tables) + " IN SHARE ROW EXCLUSIVE MODE")


def apply_accounts(payload, plan, actor=None):
    if not connection.in_atomic_block:
        raise TransferError("Record application requires the coordinated import transaction.")
    _lock_tables()
    current = plan_accounts(payload, plan.get("mappings"), plan.get("account_choices"))
    if current != plan:
        raise TransferError("The reviewed import plan is stale. Validate the package and target again.")
    if current["blockers"]:
        raise TransferError("The import plan still contains blockers.")
    updates = {row["target_user_id"] for row in plan["accounts"] if row["action"] == "update"}
    before = _auth_digest(profile_updates=updates)
    User, mappings, created, updated, skipped, reused = get_user_model(), {}, [], [], [], []
    sources = {row["key"]: row for row in payload["accounts"]}
    for row in plan["accounts"]:
        source = sources[row["source_key"]]
        if row["action"] == "skip":
            skipped.append(source["key"])
            continue
        if row["action"] in {"map", "update"}:
            user = User.objects.select_for_update().get(pk=row["target_user_id"])
            if row["action"] == "update":
                # This exact field allowlist avoids save/signal side effects and
                # retains every FK, credential, authority flag and access grant.
                User.objects.filter(pk=user.pk).update(**{field: source[field] for field in PROFILE_FIELDS})
                updated.append(source["key"])
            else:
                reused.append(source["key"])
        else:
            user = User(username=source["username"], **{field: source[field] for field in PROFILE_FIELDS},
                        date_joined=require_timestamp(source["date_joined"], "Account date"),
                        is_active=False, is_staff=False, is_superuser=False)
            user.set_unusable_password()
            user.full_clean()
            for field in ("username", *PROFILE_FIELDS):
                setattr(user, field, source[field])
            user.save(force_insert=True)
            created.append(source["key"])
        mappings[source["key"]] = user.pk
    created_ids = [mappings[key] for key in created]
    if _auth_digest(exclude_users=created_ids, profile_updates=updates) != before:
        raise TransferError("Existing account authority or unrelated records changed during import; no changes were committed.")
    connection.check_constraints()
    result = {
        "mode": "accounts", "version": 1, "package_digest": digest(payload),
        "account_choices": plan["account_choices"], "created_counts": {"accounts": len(created)} if created else {},
        "updated_counts": {"accounts": len(updated)} if updated else {},
        "reused_counts": {"accounts": len(reused)} if reused else {},
        "created_account_keys": created, "updated_account_keys": updated, "skipped_account_keys": skipped,
        "user_mappings": mappings, "target_digest": _auth_digest(),
    }
    # Check the newly created users as well as preserved identities before the
    # caller writes its receipt and commits. Save hooks may evolve independently.
    verify_accounts(payload, result)
    return result


def verify_accounts(payload, result):
    from .records import validate_records
    from qc_tool.frontend.accounts.authorization.roles import Role
    payload = validate_records(payload)
    require_keys(result, RESULT_FIELDS, "Committed user import summary")
    if payload["profile"] != "accounts" or result["mode"] != "accounts" or type(result["version"]) is not int or result["version"] != 1 or result["package_digest"] != digest(payload):
        raise TransferError("The committed user import does not match its source package.")
    choices = _choices(payload, {}, result["account_choices"])
    if choices != result["account_choices"] or set(choices) != {row["key"] for row in payload["accounts"]}:
        raise TransferError("Committed user choices are incomplete or inconsistent.")
    expected = {action: [key for key, row in choices.items() if row["action"] == action] for action in ACTIONS}
    for field, action in (("created_account_keys", "import"), ("updated_account_keys", "replace"), ("skipped_account_keys", "skip")):
        if result[field] != expected[action]:
            raise TransferError("Committed user choices differ from their receipt.")
    mappings = result["user_mappings"]
    included = set(choices) - set(expected["skip"])
    if (not isinstance(mappings, dict) or set(mappings) != included or any(type(pk) is not int or pk <= 0 for pk in mappings.values())
            or len(set(mappings.values())) != len(mappings)):
        raise TransferError("Committed account identity evidence is incomplete or inconsistent.")
    users = {user.pk: user for user in get_user_model().objects.filter(pk__in=mappings.values()).prefetch_related("groups", "user_permissions", "product_grants")}
    if set(users) != set(mappings.values()):
        raise TransferError("An imported or mapped target account is missing.")
    for source in payload["accounts"]:
        choice = choices[source["key"]]
        if choice["action"] == "skip":
            continue
        user = users[mappings[source["key"]]]
        if choice["action"] in {"reuse", "replace"} and choice["target_id"] != user.pk:
            raise TransferError("A committed user identity mapping differs from its receipt.")
        if choice["action"] == "import":
            if (user.is_active or user.is_staff or user.is_superuser or user.has_usable_password()
                    or user.user_permissions.exists() or user.product_grants.exists()
                    or {group.name for group in user.groups.all()} != {Role.DEFAULT.value}):
                raise TransferError("An imported account's inactive access boundary has changed.")
            if any(json_value(getattr(user, field)) != source[field] for field in ("username", "date_joined")):
                raise TransferError("An imported account differs from its committed source profile.")
        if choice["action"] in {"import", "replace"} and any(getattr(user, field) != source[field] for field in PROFILE_FIELDS):
            raise TransferError("An imported account differs from its committed source profile.")
    for field, action in (("created_counts", "import"), ("updated_counts", "replace"), ("reused_counts", "reuse")):
        if result[field] != ({"accounts": len(expected[action])} if expected[action] else {}):
            raise TransferError("Committed user counts differ from the verified import.")
    if result["target_digest"] != _auth_digest():
        raise TransferError("Account or access evidence changed after commit; keep maintenance enabled and investigate.")
    return {"verified_counts": result["created_counts"], "updated_counts": result["updated_counts"], "records_digest": digest(payload["records"])}
