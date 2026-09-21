"""An explicit SQL-dump import into a fresh, initialized application database."""

from dataclasses import dataclass, field
from io import StringIO

from django.apps import apps
from django.conf import settings
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.color import no_style
from django.core.management import call_command
from django.db import connections, transaction

from qc_tool.database.deployment import check_draft_tables
from qc_tool.database.policy import load_policy
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import UserProductGrant, UserProfile, UserRegionGrant
from qc_tool.frontend.dashboard.models import Delivery, Job, S3Info

from .accounts import prepare_accounts
from .records import prepare_records
from .values import bounded_text, integer, timestamp


@dataclass(repr=False)
class PreparedImport:
    accounts: object = field(repr=False)
    storage: list = field(repr=False)
    deliveries: list = field(repr=False)
    jobs: list = field(repr=False)
    admin_logs: list = field(repr=False)
    source_content_types: dict = field(repr=False)
    report: dict


def prepare_import(dump, access_map=None):
    """Validate/convert all rows without executing SQL or consulting a target."""
    for required in ("auth_user", "dashboard_delivery", "dashboard_job"):
        if required not in dump.tables:
            raise ValueError(f"Required source table is missing: {required}")
    accounts = prepare_accounts(dump, access_map=access_map)
    storage, deliveries, jobs, stats, states = prepare_records(dump, {user.pk for user in accounts.users})
    content_types = {
        integer(row["id"], "django_content_type"): (row["app_label"], row["model"])
        for row in dump.tables.get("django_content_type", [])
    }
    logs = _prepare_logs(dump, {user.pk for user in accounts.users}, content_types)
    report = {
        "mode": "dry_run", "source_sha256": dump.source_sha256,
        "source_size_bytes": dump.source_size_bytes, "source_tables": dump.counts,
        "planned": {
            "users": len(accounts.users), "profiles": len(accounts.profiles),
            "deliveries": len(deliveries), "jobs": len(jobs), "storage_sources": len(storage),
            "admin_log_entries": len(logs),
            "product_grants": len(accounts.product_grants), "region_grants": len(accounts.region_grants),
        },
        "historical_records": stats, "source_job_states": states,
        "access": {
            "roles": {role: sum(role in roles for roles in accounts.role_names.values())
                      for role in Role.values()},
            "inert_legacy_groups": len(accounts.legacy_groups),
            "legacy_group_permissions_not_activated": accounts.legacy_group_permission_count,
            "direct_permission_links_to_resolve": sum(map(len, accounts.permissions.values())),
        },
        "omitted": {
            "legacy_api_credentials": len(dump.tables.get("dashboard_apiuser", [])),
            "sessions": len(dump.tables.get("django_session", [])),
            "migration_history": len(dump.tables.get("django_migrations", [])),
            "s3_credential_pairs": len(storage),
        },
        "warnings": [
            "Delivery ZIPs and QC reports are not in the SQL dump; downloads cannot be restored.",
            "Submission dates are preserved as history. No verified submission receipts, approvals, products or delivery plans are created.",
            "Only reported product units are converted from legacy AOI values; ZIP-verified units and content hashes remain empty.",
            "Legacy API keys and sessions are not imported. S3 locations are retained with blank credentials.",
            "Product and region assignments require a reviewed access map or later administrator assignment; none are inferred from upload history.",
            "The source dump remains the audit record for unmapped roles, permissions and unavailable files.",
            *accounts.warnings,
        ],
    }
    return PreparedImport(accounts, storage, deliveries, jobs, logs, content_types, report)


def apply_import(plan, *, database="default", target_database):
    """Commit once to an empty target. A rerun/nonempty target is never merged."""
    connection = connections[database]
    if str(connection.settings_dict["NAME"]) != str(target_database):
        raise ValueError("Target database name does not match the configured database; no data was written.")
    phase = load_policy()["phase"]
    if phase == "draft" and settings.IS_SECURE_ENVIRONMENT:
        raise ValueError("Freeze the release schema before a production import. Draft imports are for development/test rehearsals only.")
    if phase == "released":
        call_command("database", "check", database=database, stdout=StringIO())
    check_draft_tables(connection)
    with transaction.atomic(using=database):
        if connection.vendor == "postgresql":
            # The target is offline. Lock all application tables before the
            # emptiness check, preventing concurrent writers during import.
            tables = sorted({model._meta.db_table for model in apps.get_models(include_auto_created=True)
                             if model._meta.managed and model._meta.can_migrate(connection)})
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '5s'")
                cursor.execute("LOCK TABLE " + ", ".join(connection.ops.quote_name(table) for table in tables) + " IN EXCLUSIVE MODE")
        _require_fresh_target(database, connection)
        result = _write_rows(plan, database, connection)
    return {**plan.report, "mode": "applied", "imported": result}


def _require_fresh_target(database, connection):
    allowed = {"auth.group", "auth.permission", "auth.group_permissions", "contenttypes.contenttype"}
    for model in apps.get_models(include_auto_created=True):
        if not model._meta.managed or not model._meta.can_migrate(connection) or model._meta.label_lower in allowed:
            continue
        if model._default_manager.using(database).exists():
            raise ValueError("The target contains existing records. Use a fresh initialized database; nothing was imported.")
    groups = set(Group.objects.using(database).values_list("name", flat=True))
    if groups != set(Role.values()):
        raise ValueError("The target must contain only the standard role groups created by database apply.")


def _write_rows(plan, database, connection):
    user_model = get_user_model()
    account = plan.accounts
    groups = dict(Group.objects.using(database).values_list("name", "pk"))
    for name in account.legacy_groups.values():
        groups[name] = Group.objects.using(database).create(name=name).pk
    for model, rows in (
        (user_model, account.users), (UserProfile, account.profiles),
        (S3Info, plan.storage), (Delivery, plan.deliveries), (Job, plan.jobs),
        (UserProductGrant, account.product_grants), (UserRegionGrant, account.region_grants),
    ):
        model.objects.using(database).bulk_create(rows, batch_size=500)
    memberships = {(user_id, groups[role]) for user_id, roles in account.role_names.items() for role in roles}
    memberships.update((user_id, groups[account.legacy_groups[group_id]]) for user_id, group_id in account.legacy_memberships)
    membership_model = user_model.groups.through
    membership_model.objects.using(database).bulk_create([
        membership_model(user_id=user_id, group_id=group_id) for user_id, group_id in sorted(memberships)
    ], batch_size=500)
    permission_ids = {
        (app_label, model, codename): ident for ident, app_label, model, codename in
        Permission.objects.using(database).values_list("pk", "content_type__app_label", "content_type__model", "codename")
    }
    direct_model = user_model.user_permissions.through
    direct_rows, skipped = [], 0
    for user_id, keys in account.permissions.items():
        for key in keys:
            if key in permission_ids:
                direct_rows.append(direct_model(user_id=user_id, permission_id=permission_ids[key]))
            else:
                skipped += 1
    direct_model.objects.using(database).bulk_create(direct_rows, batch_size=500)
    ct_ids = {(row.app_label, row.model): row.pk for row in ContentType.objects.using(database).all()}
    # Only retained objects with preserved primary keys can have live audit
    # links. Framework/group IDs are regenerated and can identify unrelated
    # target objects; old logs for deleted objects have the same risk.
    retained_log_objects = {
        ("auth", "user"): {str(user.pk) for user in account.users},
        ("dashboard", "delivery"): {str(delivery.pk) for delivery in plan.deliveries},
        ("dashboard", "job"): {
            value for job in plan.jobs for value in (str(job.pk), job.pk.hex)
        },
        ("dashboard", "s3info"): {str(source.pk) for source in plan.storage},
    }
    for entry, source_key in plan.admin_logs:
        entry.content_type_id = (
            ct_ids.get(source_key)
            if entry.object_id in retained_log_objects.get(source_key, ())
            else None
        )
    LogEntry.objects.using(database).bulk_create([entry for entry, _ in plan.admin_logs], batch_size=500)
    models = [user_model, UserProfile, S3Info, Delivery, Job, Group, membership_model,
              direct_model, UserProductGrant, UserRegionGrant, LogEntry]
    with connection.cursor() as cursor:
        for sql in connection.ops.sequence_reset_sql(no_style(), models):
            cursor.execute(sql)
    counts = dict(plan.report["planned"])
    counts.update(direct_permissions=len(direct_rows), unmapped_direct_permissions=skipped,
                  inert_legacy_groups=len(account.legacy_groups), legacy_group_permissions_not_activated=account.legacy_group_permission_count)
    expected = [(user_model, len(account.users)), (UserProfile, len(account.profiles)),
                (Delivery, len(plan.deliveries)), (Job, len(plan.jobs)), (S3Info, len(plan.storage)),
                (LogEntry, len(plan.admin_logs))]
    if any(model.objects.using(database).count() != count for model, count in expected):
        raise ValueError("Import reconciliation failed; the transaction was rolled back.")
    return counts


def _prepare_logs(dump, user_ids, content_types):
    logs, seen = [], set()
    for row in dump.tables.get("django_admin_log", []):
        loc = "django_admin_log"
        ident = integer(row["id"], loc)
        user_id = integer(row["user_id"], loc)
        content_type = integer(row["content_type_id"], loc) if row["content_type_id"] is not None else None
        flag = integer(row["action_flag"], loc)
        if ident in seen or user_id not in user_ids or flag not in (1, 2, 3) or content_type is not None and content_type not in content_types:
            raise ValueError(f"{loc}: invalid row or relationship")
        seen.add(ident)
        logs.append((LogEntry(
            id=ident, user_id=user_id, action_time=timestamp(row["action_time"], loc),
            object_id=bounded_text(row["object_id"], loc, 10000, nullable=True),
            object_repr=bounded_text(row["object_repr"], loc, 200), action_flag=flag,
            change_message=bounded_text(row["change_message"], loc, 1000000),
        ), content_types.get(content_type)))
    return logs
